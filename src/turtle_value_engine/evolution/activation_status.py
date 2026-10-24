"""Read-only activation state inspection (Phase 7-C4-B).

This module answers one operator question without touching a single byte:
*what is the state of the local profile activation store right now?*  It
consumes only the persisted Phase 7-C4-A artifacts — intent journals,
receipts, content-addressed before-images, rollback recovery intents and
rollback outcomes — plus the observed bytes of the one explicitly supplied
private project config, and classifies them into a small, stable, versioned
projection with Chinese plain-language guidance.

Boundaries, made explicit:

* **Strictly read-only.**  The inspection performs no ``mkdir``, no lock
  creation, no ``flock``, no repair, no JSON rewrite, no config write and no
  provider/model/network call of any kind.  A missing store stays missing;
  a repeated invocation over unchanged bytes produces byte-identical output.
* **Byte truth, never inference.**  ``ACTIVATED_VERIFIED`` /
  ``ROLLED_BACK_VERIFIED`` require the observed config bytes to equal the
  receipt-bound hashes AND every referenced artifact to validate.  Wherever
  the bytes cannot prove a state, the classifier reports the pending,
  diverged, ambiguous or corrupt class instead of guessing success.
  Activated bytes of an activation whose valid rollback outcome is present
  do **not** prove a current activation (the executor reuses the same
  deterministic identities on re-apply, so a genuine re-apply and an
  external restoration are byte-identical): they classify as
  ``CONFIG_DIVERGED`` with ``ROLLED_BACK_ACTIVATION_BYTES_PRESENT`` unless a
  distinct matching activation without a rollback outcome — independently
  verifiable later activation history — carries the state.
* **No verified green alongside problems.**  The projection contract pins
  every informational status (``NO_HISTORY`` / ``ACTIVATED_VERIFIED`` /
  ``ROLLED_BACK_VERIFIED``) to an empty ``problems`` list; receipt
  diagnostics supplied through ``--receipt`` are additive facts inside
  ``receipt_inspection`` and never enter the store-level ``problems``.
* **Owner authority is out of scope.**  A historical receipt is audit
  evidence, not present owner consent: the projection fixes
  ``owner_authority_revalidated=false`` and never re-runs signature
  verification, re-authorization or any fresh plan derivation.
* **No global atomicity claim.**  The observation is a single read pass over
  each artifact; a concurrent apply/rollback may change bytes between reads.
  ``global_atomic_snapshot_claimed=false`` records that limit honestly.

Fail-closed guards are the executor's own (reused read-only): a symlinked or
non-directory activation root / store descendant, a symlinked or non-regular
config target, or paths aliasing into checked-in repository trees raise
:class:`ActivationExecutionError` (CLI exit class 2).  Corruption *inside*
an otherwise well-formed store is never raised away — it is reported as the
``CORRUPT_OR_UNVERIFIABLE`` status with named problems so the operator sees
exactly which artifact failed which check.
"""

from __future__ import annotations

import json
import stat
import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes

from .activation_execution import (
    ActivationExecutionError,
    ProfileActivationIntentV1,
    ProfileActivationReceiptV1,
    ProfileActivationRollbackIntentV1,
    ProfileActivationRollbackOutcomeV1,
    _build_rollback_intent,
    _build_rollback_outcome,
    _guard_activation_root,
    _guard_activation_store,
    _guard_target_config,
    _sha256_hex,
)

HASH_PATTERN = r"^[0-9a-f]{64}$"

#: The five store directories the executor owns.  ``locks`` is verified for
#: containment but never scanned: lock entries are operational state, not
#: activation history, and leftover lock files are normal.
_STATUS_STORE_DIRS: tuple[str, ...] = (
    "locks",
    "journal",
    "receipts",
    "before-images",
    "rollbacks",
)

ACTIVATION_STATUS_NO_HISTORY = "NO_HISTORY"
ACTIVATION_STATUS_ACTIVATED_VERIFIED = "ACTIVATED_VERIFIED"
ACTIVATION_STATUS_ROLLED_BACK_VERIFIED = "ROLLED_BACK_VERIFIED"
ACTIVATION_STATUS_RECEIPT_FINALIZATION_PENDING = "RECEIPT_FINALIZATION_PENDING"
ACTIVATION_STATUS_APPLY_RESUMABLE = "APPLY_RESUMABLE"
ACTIVATION_STATUS_ROLLBACK_FINALIZATION_PENDING = (
    "ROLLBACK_FINALIZATION_PENDING"
)
ACTIVATION_STATUS_CONFIG_DIVERGED = "CONFIG_DIVERGED"
ACTIVATION_STATUS_AMBIGUOUS_HISTORY = "AMBIGUOUS_HISTORY"
ACTIVATION_STATUS_CORRUPT_OR_UNVERIFIABLE = "CORRUPT_OR_UNVERIFIABLE"

#: Stable status values (goal Phase 7-C4-B §2, items 1–8 plus the honest
#: escape that a not-provable classification must never guess).
ACTIVATION_STATUS_VALUES: tuple[str, ...] = (
    ACTIVATION_STATUS_NO_HISTORY,
    ACTIVATION_STATUS_ACTIVATED_VERIFIED,
    ACTIVATION_STATUS_ROLLED_BACK_VERIFIED,
    ACTIVATION_STATUS_RECEIPT_FINALIZATION_PENDING,
    ACTIVATION_STATUS_APPLY_RESUMABLE,
    ACTIVATION_STATUS_ROLLBACK_FINALIZATION_PENDING,
    ACTIVATION_STATUS_CONFIG_DIVERGED,
    ACTIVATION_STATUS_AMBIGUOUS_HISTORY,
    ACTIVATION_STATUS_CORRUPT_OR_UNVERIFIABLE,
)

#: Verified-informational outcomes (CLI exit 0).  Every pending, diverged,
#: ambiguous or corrupt outcome is exit 1; unusable input is exit 2.
INFORMATIONAL_ACTIVATION_STATUSES: frozenset[str] = frozenset(
    {
        ACTIVATION_STATUS_NO_HISTORY,
        ACTIVATION_STATUS_ACTIVATED_VERIFIED,
        ACTIVATION_STATUS_ROLLED_BACK_VERIFIED,
    }
)

_GUIDANCE_ZH: dict[str, tuple[str, ...]] = {
    ACTIVATION_STATUS_NO_HISTORY: (
        "该配置在本激活存储中没有任何激活或回滚历史，无需恢复操作。",
        "如需启用新策略，请先运行 activate-profile 的只读预览（默认、零写入）。",
    ),
    ACTIVATION_STATUS_ACTIVATED_VERIFIED: (
        "激活已完成且证据一致：回执、意图日志与内容寻址备份均有效，"
        "当前配置字节等于激活后哈希。",
        "状态检查不重新验证所有者签名授权；历史回执不证明当前所有者同意。",
        "如需恢复激活前状态，可执行回执绑定的 rollback-activation 命令"
        "（显式、字节精确）。",
    ),
    ACTIVATION_STATUS_ROLLED_BACK_VERIFIED: (
        "回滚已完成并经字节验证：当前配置等于激活前哈希，"
        "默认策略已恢复，回滚结果有效。",
    ),
    ACTIVATION_STATUS_RECEIPT_FINALIZATION_PENDING: (
        "配置已被替换为激活后字节，但回执尚未发布——"
        "应用在配置替换后、回执发布前被中断。",
        "重新执行同一 apply 命令可从意图日志确定性补写回执，"
        "不会再次修改配置；本命令不做任何修复。",
    ),
    ACTIVATION_STATUS_APPLY_RESUMABLE: (
        "存在未完成的激活意图，且配置仍保持激活前字节——"
        "应用在配置替换之前被中断。",
        "可重新执行同一 apply 命令恢复；恢复成功仍要求当时的授权链"
        "（计划、决策记录、证据束、信任根）现在依然有效。",
    ),
    ACTIVATION_STATUS_ROLLBACK_FINALIZATION_PENDING: (
        "配置已恢复为激活前字节，回滚恢复意图存在，但回滚结果尚未发布——"
        "回滚在恢复之后、结果发布之前被中断。",
        "重新执行同一 rollback 命令可确定性补写结果，"
        "不会再次修改配置；本命令不做任何修复。",
    ),
    ACTIVATION_STATUS_CONFIG_DIVERGED: (
        "当前配置字节与本存储可证明的任何激活/回滚状态都不一致，"
        "可能被手工修改。",
        "状态检查不做任何修复；请人工比对 before-images/ 下的内容寻址备份后"
        "决定恢复方式。",
    ),
    ACTIVATION_STATUS_AMBIGUOUS_HISTORY: (
        "存在多份未完成的激活意图，无法判断哪一份代表当前意图。",
        "请人工检查 journal/ 目录；执行器会拒绝进一步激活直至歧义消除，"
        "本命令不做任何裁决。",
    ),
    ACTIVATION_STATUS_CORRUPT_OR_UNVERIFIABLE: (
        "激活存储中存在损坏、被篡改、越界或无法验证的工件"
        "（见 problems 列表的具体条目）。",
        "状态检查不做任何修复；请按 problems 逐项人工处理后再判断状态。",
    ),
}


class ActivationFocalStateV1(BaseModel):
    """Verified identities of the one activation a classification is about."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    activation_id: StrictStr = Field(min_length=1, max_length=168)
    activated_default_profile: StrictStr = Field(min_length=1, max_length=128)
    activated_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    prior_default_profile: StrictStr = Field(min_length=1, max_length=128)
    prior_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    before_image_name: StrictStr = Field(min_length=1, max_length=256)
    before_image_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    journal_present: bool
    receipt_present: bool
    before_image_present: bool
    rollback_id: StrictStr | None = Field(
        default=None, min_length=1, max_length=168
    )
    rollback_outcome_present: bool = False
    rollback_intent_present: bool = False


class ActivationReceiptInspectionV1(BaseModel):
    """Additive facts about one explicitly supplied receipt file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_path: StrictStr = Field(min_length=1, max_length=2_048)
    activation_id: StrictStr = Field(min_length=1, max_length=168)
    relevant_to_config: bool
    current_config_matches_activated: bool
    journal_present: bool
    before_image_verified: bool
    store_copy_present: bool
    store_copy_matches: bool
    rollback_outcome_present: bool
    rollback_intent_present: bool


class ProfileActivationStatusV1(BaseModel):
    """The versioned, deterministic, read-only activation status projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_activation_status_v1"] = (
        "profile_activation_status_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    status: StrictStr = Field(min_length=1, max_length=64)
    project_config_path: StrictStr = Field(min_length=1, max_length=2_048)
    current_config_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    current_default_profile: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )
    activation_root_present: bool
    relevant_histories: int = Field(ge=0, le=1_000)
    unrelated_histories: int = Field(ge=0, le=1_000)
    pending_activation_ids: list[StrictStr] = Field(default_factory=list)
    problems: list[StrictStr] = Field(default_factory=list)
    observations: list[StrictStr] = Field(default_factory=list)
    guidance_zh: list[StrictStr] = Field(min_length=1, max_length=16)
    focal: ActivationFocalStateV1 | None = None
    receipt_inspection: ActivationReceiptInspectionV1 | None = None
    owner_authority_revalidated: Literal[False] = False
    global_atomic_snapshot_claimed: Literal[False] = False
    read_only_observation: Literal[True] = True
    execution_performed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_status_projection(self) -> Self:
        if self.status not in ACTIVATION_STATUS_VALUES:
            raise ValueError(f"unknown activation status: {self.status}")
        if self.status not in _GUIDANCE_ZH:
            raise ValueError(f"status carries no guidance: {self.status}")
        if (
            self.status in INFORMATIONAL_ACTIVATION_STATUSES
            and self.problems
        ):
            raise ValueError(
                "an informational activation status must never carry "
                f"store-level problems: {self.status} with {self.problems}"
            )
        for field in ("pending_activation_ids", "problems", "observations"):
            value = getattr(self, field)
            if value != sorted(set(value)):
                raise ValueError(f"{field} must be sorted and deduplicated")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("status content_sha256 does not match content")
        return self

    def serialized_bytes(self) -> bytes:
        return (
            json.dumps(
                self.model_dump(mode="json", warnings=False),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")


# ---------------------------------------------------------------------------
# Read-only scanning helpers
# ---------------------------------------------------------------------------


def _entry_kind(entry: Path) -> str:
    """lstat-based kind: "absent" | "symlink" | "file" | "directory" | "other"."""

    try:
        metadata = entry.lstat()
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "other"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    return "other"


def _scan_regular_json_entries(
    directory: Path,
    label: str,
    problems: list[str],
) -> list[tuple[str, Path]]:
    """Regular non-symlink ``*.json`` entries, naming every foreign entry.

    A symlinked or otherwise non-regular store artifact, and any unexpected
    entry, is a named *problem* (``CORRUPT_OR_UNVERIFIABLE``), never a reason
    to stop scanning or to silently skip the anomaly.
    """

    found: list[tuple[str, Path]] = []
    for entry in sorted(directory.iterdir()):
        kind = _entry_kind(entry)
        if kind == "symlink":
            problems.append(f"{label}_FILE_SYMLINK:{entry.name}")
            continue
        if kind != "file" or entry.suffix != ".json":
            problems.append(f"{label}_DIR_FOREIGN_ENTRY:{entry.name}")
            continue
        found.append((entry.name, entry))
    return found


def _verify_before_image(
    root: Path,
    receipt: ProfileActivationReceiptV1,
    *,
    require_present: bool,
    record_problems: bool,
    problems: list[str],
) -> bool:
    """Full before-image verification; optionally records named problems.

    ``require_present`` encodes the executor's own write order (journal →
    before-image → replace → receipt): a *finished* activation (receipt
    published) and any activation whose replacement provably happened (the
    observed config equals the activated hash) must carry a valid image,
    while an unfinished intent whose config still holds the prior bytes may
    legitimately have crashed before the image was persisted — absence there
    is expected interruption state, never corruption.  When an image *is*
    present it is always fully verified.
    """

    name = receipt.before_image_name
    if Path(name).name != name or name in {"", ".", ".."}:
        if record_problems:
            problems.append(f"BEFORE_IMAGE_NAME_INVALID:{name}")
        return False
    directory = root / "before-images"
    path = directory / name
    kind = _entry_kind(path)
    if kind == "absent":
        if require_present and record_problems:
            problems.append(f"BEFORE_IMAGE_MISSING:before-images/{name}")
        return False
    if kind == "symlink":
        if record_problems:
            problems.append(f"BEFORE_IMAGE_FILE_SYMLINK:before-images/{name}")
        return False
    if kind != "file":
        if record_problems:
            problems.append(
                f"BEFORE_IMAGE_FILE_NOT_REGULAR:before-images/{name}"
            )
        return False
    try:
        if not path.resolve().is_relative_to(directory.resolve()):
            if record_problems:
                problems.append(
                    f"BEFORE_IMAGE_OUT_OF_ROOT:before-images/{name}"
                )
            return False
        image_bytes = path.read_bytes()
    except OSError:
        if record_problems:
            problems.append(f"BEFORE_IMAGE_MISSING:before-images/{name}")
        return False
    if _sha256_hex(image_bytes) != receipt.before_image_sha256:
        if record_problems:
            problems.append(f"BEFORE_IMAGE_HASH_MISMATCH:before-images/{name}")
        return False
    if _sha256_hex(image_bytes) != receipt.prior_config_sha256:
        if record_problems:
            problems.append(
                f"BEFORE_IMAGE_CONTENT_MISMATCH:before-images/{name}"
            )
        return False
    try:
        parsed = tomllib.loads(image_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        if record_problems:
            problems.append(
                f"BEFORE_IMAGE_CONTENT_MISMATCH:before-images/{name}"
            )
        return False
    profiles_section = parsed.get("profiles")
    if not isinstance(profiles_section, dict) or profiles_section.get(
        "default"
    ) != receipt.prior_default_profile:
        if record_problems:
            problems.append(
                f"BEFORE_IMAGE_CONTENT_MISMATCH:before-images/{name}"
            )
        return False
    return True


def _scan_store(
    root: Path, config_path: Path, current_hash: str
) -> dict[str, object]:
    """One read pass over the persisted artifacts (no writes, no repair)."""

    problems: list[str] = []

    relevant_intents: list[ProfileActivationIntentV1] = []
    unrelated_activation_ids: set[str] = set()
    relevant_receipts: dict[str, ProfileActivationReceiptV1] = {}
    relevant_outcomes: dict[str, ProfileActivationRollbackOutcomeV1] = {}
    relevant_rollback_intents: dict[str, ProfileActivationRollbackIntentV1] = {}

    journal_dir = root / "journal"
    if journal_dir.is_dir():
        for name, path in _scan_regular_json_entries(
            journal_dir, "JOURNAL", problems
        ):
            try:
                intent = ProfileActivationIntentV1.model_validate(
                    json.loads(path.read_bytes())
                )
            except Exception:
                problems.append(f"JOURNAL_CORRUPT:journal/{name}")
                continue
            if path.stem != intent.intent_id:
                problems.append(f"JOURNAL_NAME_MISMATCH:journal/{name}")
                continue
            if Path(intent.receipt.project_config_path) == config_path:
                relevant_intents.append(intent)
            else:
                unrelated_activation_ids.add(intent.receipt.activation_id)

    receipts_dir = root / "receipts"
    if receipts_dir.is_dir():
        for name, path in _scan_regular_json_entries(
            receipts_dir, "RECEIPTS", problems
        ):
            try:
                receipt = ProfileActivationReceiptV1.model_validate(
                    json.loads(path.read_bytes())
                )
            except Exception:
                problems.append(f"RECEIPT_CORRUPT:receipts/{name}")
                continue
            if path.stem != receipt.activation_id:
                problems.append(f"RECEIPT_NAME_MISMATCH:receipts/{name}")
                continue
            if Path(receipt.project_config_path) == config_path:
                relevant_receipts[receipt.activation_id] = receipt
            else:
                unrelated_activation_ids.add(receipt.activation_id)

    before_images_dir = root / "before-images"
    if before_images_dir.is_dir():
        for entry in sorted(before_images_dir.iterdir()):
            kind = _entry_kind(entry)
            if kind == "symlink":
                problems.append(
                    f"BEFORE_IMAGE_FILE_SYMLINK:before-images/{entry.name}"
                )
            elif kind != "file" or entry.suffix != ".toml":
                problems.append(
                    f"BEFORE_IMAGES_DIR_FOREIGN_ENTRY:before-images/{entry.name}"
                )

    rollback_dir = root / "rollbacks"
    if rollback_dir.is_dir():
        for entry in sorted(rollback_dir.iterdir()):
            kind = _entry_kind(entry)
            if kind == "symlink":
                problems.append(
                    f"ROLLBACK_FILE_SYMLINK:rollbacks/{entry.name}"
                )
                continue
            if kind != "file" or not entry.name.endswith(".json"):
                problems.append(
                    f"ROLLBACKS_DIR_FOREIGN_ENTRY:rollbacks/{entry.name}"
                )
                continue
            if entry.name.endswith(".intent.json"):
                stem = entry.name[: -len(".intent.json")]
                model_cls: type[
                    ProfileActivationRollbackOutcomeV1
                ] | type[ProfileActivationRollbackIntentV1] = (
                    ProfileActivationRollbackIntentV1
                )
                corrupt_code = "ROLLBACK_INTENT_CORRUPT"
            else:
                stem = entry.stem
                model_cls = ProfileActivationRollbackOutcomeV1
                corrupt_code = "ROLLBACK_OUTCOME_CORRUPT"
            try:
                model = model_cls.model_validate(json.loads(entry.read_bytes()))
            except Exception:
                problems.append(f"{corrupt_code}:rollbacks/{entry.name}")
                continue
            if stem != model.rollback_id:
                problems.append(
                    f"ROLLBACK_NAME_MISMATCH:rollbacks/{entry.name}"
                )
                continue
            if Path(model.project_config_path) != config_path:
                continue
            if isinstance(model, ProfileActivationRollbackOutcomeV1):
                relevant_outcomes[model.rollback_id] = model
            else:
                relevant_rollback_intents[model.rollback_id] = model

    # Journal <-> receipt association (relevant histories only).
    for activation_id, receipt in relevant_receipts.items():
        journal = next(
            (
                intent
                for intent in relevant_intents
                if intent.receipt.activation_id == activation_id
            ),
            None,
        )
        if journal is None:
            problems.append(f"RECEIPT_WITHOUT_JOURNAL:receipts/{activation_id}")
        elif journal.receipt != receipt:
            problems.append(f"RECEIPT_JOURNAL_MISMATCH:receipts/{activation_id}")

    # Before-image verification for every relevant activation, honouring the
    # executor's write order: finished activations and provably-replaced
    # configs must carry a valid image; an unfinished, unreplaced intent may
    # legitimately have crashed before the image was persisted.
    verified_before_images: set[str] = set()
    for intent in relevant_intents:
        receipt = intent.receipt
        require_present = (
            receipt.activation_id in relevant_receipts
            or current_hash == receipt.activated_config_sha256
        )
        if _verify_before_image(
            root,
            receipt,
            require_present=require_present,
            record_problems=True,
            problems=problems,
        ):
            verified_before_images.add(receipt.before_image_name)

    # Rollback artifacts must associate with a relevant receipt and match the
    # deterministic expectation recomputed from it.
    outcome_by_activation: dict[str, ProfileActivationRollbackOutcomeV1] = {}
    for rollback_id, outcome in relevant_outcomes.items():
        receipt = relevant_receipts.get(outcome.activation_id)
        if receipt is None or receipt.content_sha256 != (
            outcome.receipt_content_sha256
        ):
            problems.append(f"ROLLBACK_UNASSOCIATED:rollbacks/{rollback_id}.json")
            continue
        expected = _build_rollback_outcome(
            receipt, Path(receipt.project_config_path).resolve()
        )
        if expected != outcome:
            problems.append(
                f"ROLLBACK_CONTENT_MISMATCH:rollbacks/{rollback_id}.json"
            )
            continue
        outcome_by_activation[outcome.activation_id] = outcome
    intent_by_activation: dict[str, ProfileActivationRollbackIntentV1] = {}
    for rollback_id, intent in relevant_rollback_intents.items():
        receipt = relevant_receipts.get(intent.activation_id)
        if receipt is None or receipt.content_sha256 != (
            intent.receipt_content_sha256
        ):
            problems.append(
                f"ROLLBACK_UNASSOCIATED:rollbacks/{rollback_id}.intent.json"
            )
            continue
        expected = _build_rollback_intent(
            receipt, Path(receipt.project_config_path).resolve()
        )
        if expected != intent:
            problems.append(
                f"ROLLBACK_CONTENT_MISMATCH:rollbacks/{rollback_id}.intent.json"
            )
            continue
        intent_by_activation[intent.activation_id] = intent

    return {
        "problems": problems,
        "relevant_intents": relevant_intents,
        "unrelated_activation_ids": unrelated_activation_ids,
        "relevant_receipts": relevant_receipts,
        "outcome_by_activation": outcome_by_activation,
        "rollback_intent_by_activation": intent_by_activation,
        "verified_before_images": verified_before_images,
    }


def _focal_state(
    intent: ProfileActivationIntentV1,
    *,
    receipts: dict[str, ProfileActivationReceiptV1],
    outcome_by_activation: dict[str, ProfileActivationRollbackOutcomeV1],
    rollback_intents: dict[str, ProfileActivationRollbackIntentV1],
    verified_before_images: set[str],
) -> ActivationFocalStateV1:
    receipt = intent.receipt
    expected_outcome = _build_rollback_outcome(
        receipt, Path(receipt.project_config_path).resolve()
    )
    rollback_id = expected_outcome.rollback_id
    return ActivationFocalStateV1(
        activation_id=receipt.activation_id,
        activated_default_profile=receipt.activated_default_profile,
        activated_config_sha256=receipt.activated_config_sha256,
        prior_default_profile=receipt.prior_default_profile,
        prior_config_sha256=receipt.prior_config_sha256,
        before_image_name=receipt.before_image_name,
        before_image_sha256=receipt.before_image_sha256,
        journal_present=True,
        receipt_present=receipt.activation_id in receipts,
        before_image_present=(
            receipt.before_image_name in verified_before_images
        ),
        rollback_id=rollback_id,
        rollback_outcome_present=receipt.activation_id in outcome_by_activation,
        rollback_intent_present=(
            receipt.activation_id in rollback_intents
        ),
    )


def _classify(
    *,
    current_hash: str,
    problems: list[str],
    scanned: dict[str, object],
) -> tuple[str, ActivationFocalStateV1 | None, list[str]]:
    """The deterministic classification over already-verified artifacts."""

    observations: list[str] = []
    relevant_intents: list[ProfileActivationIntentV1] = scanned[
        "relevant_intents"
    ]
    relevant_receipts: dict[str, ProfileActivationReceiptV1] = scanned[
        "relevant_receipts"
    ]
    outcome_by_activation: dict[str, ProfileActivationRollbackOutcomeV1] = (
        scanned["outcome_by_activation"]
    )
    rollback_intents: dict[str, ProfileActivationRollbackIntentV1] = scanned[
        "rollback_intent_by_activation"
    ]
    verified_before_images: set[str] = scanned["verified_before_images"]

    def focal_for(intent: ProfileActivationIntentV1) -> ActivationFocalStateV1:
        return _focal_state(
            intent,
            receipts=relevant_receipts,
            outcome_by_activation=outcome_by_activation,
            rollback_intents=rollback_intents,
            verified_before_images=verified_before_images,
        )

    if problems:
        focal = None
        if len(relevant_intents) == 1:
            focal = focal_for(relevant_intents[0])
        return ACTIVATION_STATUS_CORRUPT_OR_UNVERIFIABLE, focal, observations

    unfinished = sorted(
        (
            intent
            for intent in relevant_intents
            if intent.receipt.activation_id not in relevant_receipts
        ),
        key=lambda intent: intent.receipt.activation_id,
    )
    finished = [
        intent
        for intent in relevant_intents
        if intent.receipt.activation_id in relevant_receipts
    ]

    if len(unfinished) > 1:
        return (
            ACTIVATION_STATUS_AMBIGUOUS_HISTORY,
            None,
            observations,
        )
    if unfinished:
        intent = unfinished[0]
        receipt = intent.receipt
        if current_hash == receipt.activated_config_sha256:
            return (
                ACTIVATION_STATUS_RECEIPT_FINALIZATION_PENDING,
                focal_for(intent),
                observations,
            )
        if current_hash == receipt.prior_config_sha256:
            return ACTIVATION_STATUS_APPLY_RESUMABLE, focal_for(intent), observations
        observations.append("UNFINISHED_INTENT_CONFIG_DIVERGED")
        return (
            ACTIVATION_STATUS_CONFIG_DIVERGED,
            focal_for(intent),
            observations,
        )

    active = sorted(
        (
            intent
            for intent in finished
            if current_hash == intent.receipt.activated_config_sha256
        ),
        key=lambda intent: intent.receipt.activation_id,
    )
    if active:
        # A matching activation whose valid rollback outcome is present was
        # terminally rolled back: its activated bytes alone no longer prove a
        # *current* activation, because the executor deterministically reuses
        # the same identities on a genuine re-apply, leaving byte-identical
        # artifacts to an external restoration of the activated bytes.  Only
        # a matching activation WITHOUT a rollback outcome is independently
        # verifiable evidence of a current activation.
        provable = [
            intent
            for intent in active
            if intent.receipt.activation_id not in outcome_by_activation
        ]
        rolled_back = [
            intent
            for intent in active
            if intent.receipt.activation_id in outcome_by_activation
        ]
        if provable:
            if rolled_back:
                # Historical siblings of a proven current activation.
                observations.append("STALE_ROLLBACK_OUTCOME_PRESENT")
            if len(provable) > 1:
                return ACTIVATION_STATUS_AMBIGUOUS_HISTORY, None, observations
            intent = provable[0]
            if intent.receipt.activation_id in rollback_intents:
                observations.append("ROLLBACK_INTENT_PENDING_RESTORE")
            return (
                ACTIVATION_STATUS_ACTIVATED_VERIFIED,
                focal_for(intent),
                observations,
            )
        observations.append("ROLLED_BACK_ACTIVATION_BYTES_PRESENT")
        return (
            ACTIVATION_STATUS_CONFIG_DIVERGED,
            focal_for(active[0]),
            observations,
        )

    restored_pending = sorted(
        (
            intent
            for intent in finished
            if current_hash == intent.receipt.prior_config_sha256
            and intent.receipt.activation_id in rollback_intents
            and intent.receipt.activation_id not in outcome_by_activation
        ),
        key=lambda intent: intent.receipt.activation_id,
    )
    if restored_pending:
        return (
            ACTIVATION_STATUS_ROLLBACK_FINALIZATION_PENDING,
            focal_for(restored_pending[0]),
            observations,
        )

    restored_done = sorted(
        (
            intent
            for intent in finished
            if current_hash == intent.receipt.prior_config_sha256
            and intent.receipt.activation_id in outcome_by_activation
        ),
        key=lambda intent: intent.receipt.activation_id,
    )
    if restored_done:
        return (
            ACTIVATION_STATUS_ROLLED_BACK_VERIFIED,
            focal_for(restored_done[0]),
            observations,
        )

    if finished:
        prior_match = next(
            (
                intent
                for intent in finished
                if current_hash == intent.receipt.prior_config_sha256
            ),
            None,
        )
        if prior_match is not None:
            observations.append("RESTORED_WITHOUT_DURABLE_PROOF")
            return (
                ACTIVATION_STATUS_CONFIG_DIVERGED,
                focal_for(prior_match),
                observations,
            )
        observations.append("POST_ACTIVATION_CONFIG_DIVERGED")
        representative = sorted(
            finished, key=lambda item: item.receipt.activation_id
        )[0]
        return (
            ACTIVATION_STATUS_CONFIG_DIVERGED,
            focal_for(representative),
            observations,
        )

    return ACTIVATION_STATUS_NO_HISTORY, None, observations


def _inspect_receipt(
    *,
    receipt_path: Path,
    root: Path,
    config_path: Path,
    current_hash: str,
    scanned: dict[str, object],
) -> ActivationReceiptInspectionV1:
    """Facts about one explicitly supplied receipt file (additive detail).

    Receipt diagnostics are deliberately kept OUT of the store-level
    ``problems`` list: classification runs before this inspection, the
    projection contract pins every informational status to empty problems,
    and a supplied receipt file — even one bound to this config — is an
    external artifact whose facts are reported unambiguously through the
    ``ActivationReceiptInspectionV1`` booleans (a missing before-image for a
    receipt this store does not hold is an expected absence, not store
    corruption).  The store's own copies are verified, and any real store
    corruption problems recorded, by ``_scan_store`` above.
    """

    kind = _entry_kind(receipt_path)
    if kind != "file":
        raise ActivationExecutionError(
            "RECEIPT_INVALID",
            f"the supplied receipt must be a regular non-symlink file: "
            f"{receipt_path}",
        )
    try:
        receipt = ProfileActivationReceiptV1.model_validate(
            json.loads(receipt_path.read_bytes())
        )
    except Exception as exc:
        raise ActivationExecutionError(
            "RECEIPT_INVALID",
            f"the supplied receipt cannot be validated: {receipt_path} "
            f"({str(exc)[:200]})",
        ) from exc
    relevant = Path(receipt.project_config_path) == config_path
    relevant_intents: list[ProfileActivationIntentV1] = scanned[
        "relevant_intents"
    ]
    journal_present = any(
        intent.receipt.activation_id == receipt.activation_id
        for intent in relevant_intents
    )
    before_image_verified = _verify_before_image(
        root,
        receipt,
        require_present=relevant,
        record_problems=False,
        problems=[],
    )
    store_copy = root / "receipts" / f"{receipt.activation_id}.json"
    store_copy_present = _entry_kind(store_copy) == "file"
    store_copy_matches = False
    if store_copy_present:
        try:
            store_copy_matches = (
                store_copy.read_bytes() == receipt_path.read_bytes()
            )
        except OSError:
            store_copy_matches = False
    outcome_present = receipt.activation_id in scanned["outcome_by_activation"]
    intent_present = receipt.activation_id in scanned[
        "rollback_intent_by_activation"
    ]
    return ActivationReceiptInspectionV1(
        receipt_path=str(receipt_path),
        activation_id=receipt.activation_id,
        relevant_to_config=relevant,
        current_config_matches_activated=(
            current_hash == receipt.activated_config_sha256
        ),
        journal_present=journal_present,
        before_image_verified=before_image_verified,
        store_copy_present=store_copy_present,
        store_copy_matches=store_copy_matches,
        rollback_outcome_present=outcome_present,
        rollback_intent_present=intent_present,
    )


# ---------------------------------------------------------------------------
# Public read-only entrypoint
# ---------------------------------------------------------------------------


def inspect_activation_status(
    *,
    activation_root: str | Path,
    project_config_path: str | Path,
    receipt_path: str | Path | None = None,
) -> ProfileActivationStatusV1:
    """Classify the persisted activation state; strictly zero writes.

    Raises :class:`ActivationExecutionError` (CLI exit class 2) only for
    unusable *input* — a symlinked/non-directory/protected activation root,
    a store descendant that is a symlink or non-directory, or a missing/
    symlinked/non-regular/protected config target.  Every corruption inside
    an otherwise well-formed store is reported inside the
    ``CORRUPT_OR_UNVERIFIABLE`` projection instead of being raised.
    """

    root = _guard_activation_root(Path(activation_root))
    config_path = _guard_target_config(Path(project_config_path))
    # Read-only containment reuse: the executor's own guard refuses a
    # symlinked/non-directory store descendant without creating anything.
    _guard_activation_store(root, _STATUS_STORE_DIRS)

    root_present = root.exists()
    problems: list[str] = []
    observations: list[str] = []

    if root_present:
        for entry in sorted(root.iterdir()):
            if entry.name not in _STATUS_STORE_DIRS:
                problems.append(f"ACTIVATION_ROOT_FOREIGN_ENTRY:{entry.name}")
            elif _entry_kind(entry) != "directory":
                problems.append(
                    f"ACTIVATION_ROOT_ENTRY_NOT_DIRECTORY:{entry.name}"
                )

    config_bytes = config_path.read_bytes()
    current_hash = _sha256_hex(config_bytes)
    current_default: str | None = None
    try:
        parsed = tomllib.loads(config_bytes.decode("utf-8"))
        profiles_section = parsed.get("profiles")
        if isinstance(profiles_section, dict):
            default_value = profiles_section.get("default")
            if isinstance(default_value, str):
                current_default = default_value
            else:
                observations.append("CURRENT_CONFIG_DEFAULT_NOT_STRING")
        else:
            # A syntactically valid config whose ``profiles`` key is not a
            # TOML table (e.g. ``profiles = "unexpected"``) is a controlled
            # observation, never an uncaught attribute error.
            observations.append("CURRENT_CONFIG_PROFILES_NOT_TABLE")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        observations.append("CURRENT_CONFIG_TOML_UNPARSEABLE")

    scanned = _scan_store(root, config_path, current_hash)
    problems.extend(scanned["problems"])

    status, focal, classification_observations = _classify(
        current_hash=current_hash, problems=problems, scanned=scanned
    )
    observations.extend(classification_observations)

    receipt_inspection: ActivationReceiptInspectionV1 | None = None
    if receipt_path is not None:
        receipt_inspection = _inspect_receipt(
            receipt_path=Path(receipt_path),
            root=root,
            config_path=config_path,
            current_hash=current_hash,
            scanned=scanned,
        )

    unrelated: set[str] = scanned["unrelated_activation_ids"]
    if unrelated:
        observations.append("UNRELATED_HISTORIES_PRESENT")

    relevant_intents: list[ProfileActivationIntentV1] = scanned[
        "relevant_intents"
    ]
    pending_ids = sorted(
        intent.receipt.activation_id
        for intent in relevant_intents
        if intent.receipt.activation_id
        not in scanned["relevant_receipts"]
    )

    guidance = list(_GUIDANCE_ZH[status])
    if status == ACTIVATION_STATUS_AMBIGUOUS_HISTORY:
        guidance.insert(
            1,
            f"未完成的激活意图共 {len(pending_ids)} 份："
            + "、".join(pending_ids),
        )
    if (
        status == ACTIVATION_STATUS_ACTIVATED_VERIFIED
        and focal is not None
        and current_default is not None
    ):
        guidance.insert(
            0,
            f"当前默认策略为 {current_default}；激活后哈希 "
            f"{focal.activated_config_sha256}。",
        )

    payload = {
        "contract": "profile_activation_status_v1",
        "schema_version": "1.0.0",
        "status": status,
        "project_config_path": str(config_path),
        "current_config_sha256": current_hash,
        "current_default_profile": current_default,
        "activation_root_present": root_present,
        "relevant_histories": len(relevant_intents),
        "unrelated_histories": len(unrelated),
        "pending_activation_ids": pending_ids,
        "problems": sorted(set(problems)),
        "observations": sorted(set(observations)),
        "guidance_zh": guidance,
        "focal": focal.model_dump(mode="json") if focal is not None else None,
        "receipt_inspection": (
            receipt_inspection.model_dump(mode="json")
            if receipt_inspection is not None
            else None
        ),
        "owner_authority_revalidated": False,
        "global_atomic_snapshot_claimed": False,
        "read_only_observation": True,
        "execution_performed": False,
    }
    payload["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    )
    return ProfileActivationStatusV1.model_validate(payload)


__all__ = [
    "ACTIVATION_STATUS_ACTIVATED_VERIFIED",
    "ACTIVATION_STATUS_AMBIGUOUS_HISTORY",
    "ACTIVATION_STATUS_APPLY_RESUMABLE",
    "ACTIVATION_STATUS_CONFIG_DIVERGED",
    "ACTIVATION_STATUS_CORRUPT_OR_UNVERIFIABLE",
    "ACTIVATION_STATUS_NO_HISTORY",
    "ACTIVATION_STATUS_RECEIPT_FINALIZATION_PENDING",
    "ACTIVATION_STATUS_ROLLED_BACK_VERIFIED",
    "ACTIVATION_STATUS_ROLLBACK_FINALIZATION_PENDING",
    "ACTIVATION_STATUS_VALUES",
    "ActivationFocalStateV1",
    "ActivationReceiptInspectionV1",
    "INFORMATIONAL_ACTIVATION_STATUSES",
    "ProfileActivationStatusV1",
    "inspect_activation_status",
]
