"""Phase 7-C4-C: the single read-only owner-readiness summary.

One deterministic, secret-free, Chinese-first projection answers the whole
owner-readiness journey without writing a single byte anywhere:

* which published base/target profile pair and release manifest are being
  evaluated, and whether their bytes and identities are verified (a fresh
  C1 semantic audit);
* what the CDC policy question means — the target gate threshold versus
  its own S band / extreme-safety tier — including the first diverging
  behavioural contrast from the real engine boundary replay;
* whether a valid owner decision exists and whether its authority was
  actually re-attested just now (a fresh C2-R1 plan, never a historical
  receipt);
* what the activation store proves right now (the unchanged C4-B
  classification, when an activation root is supplied);
* which concrete read-only command comes next.

The summary is informational only.  It creates no authority: no exception,
signature, owner identity, READY plan of its own, lock, journal, receipt,
directory or output file.  Every previously established plan/status fact is
nested as a source fact under its established name; ``journey_state`` is a
derived view over those facts, never a new authorization decision.
``plan-activation`` / ``activate-profile`` remain the authorization
boundaries and ``activation-status`` remains the store authority.

Next-step hint composition contract (Phase 7-C4-C-R1):

* an *executable* command appears only as the final segment after the last
  full-width colon ``：`` of a step, is composed from its exact argument
  vector through :func:`shlex.join` (no raw placeholders, no shell
  operators) and names only a complete read-only operation whose required
  inputs are actually known;
* commands that persist a file (``decision-dossier``, ``plan-activation``,
  both of which *require* an operator-chosen ``--output``) are described in
  prose with their write disclosed, never displayed as paste-ready text;
* a retry/preview command advertised as replaying the observed state is
  composed only when the exact explicitly supplied CLI path inputs are
  known (the bounded :class:`ReadinessReplayInputsV1` passed by the CLI
  handler); otherwise the step stays prose.
"""

from __future__ import annotations

import hashlib
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .activation_plan import ProfileActivationPlanV1, plan_profile_activation
from .activation_status import ProfileActivationStatusV1, inspect_activation_status
from .profile_semantic_audit import (
    HASH_PATTERN,
    ProfileSemanticAuditV1,
    VersionedPolicyExceptionV1,
    _parse_profile,
    audit_profile_semantics,
)

_HASH_PATTERN = HASH_PATTERN

JOURNEY_STATE_VALUES: frozenset[str] = frozenset(
    {
        "OWNER_DECISION_REQUIRED",
        "REJECTED_BY_OWNER",
        "DECISION_CONFLICT",
        "OWNER_AUTHORITY_NOT_PROVEN",
        "PUBLISHED_PAIR_BLOCKED",
        "ACTIVATION_BLOCKED",
        "RECOVERY_PENDING",
        "STORE_NEEDS_ATTENTION",
        "ALREADY_APPLIED",
        "ROLLED_BACK",
        "PREVIEW_READY",
    }
)

_PENDING_STORE_STATUSES = frozenset(
    {
        "RECEIPT_FINALIZATION_PENDING",
        "APPLY_RESUMABLE",
        "ROLLBACK_FINALIZATION_PENDING",
    }
)
_ATTENTION_STORE_STATUSES = frozenset(
    {
        "CONFIG_DIVERGED",
        "AMBIGUOUS_HISTORY",
        "CORRUPT_OR_UNVERIFIABLE",
    }
)
_NO_DECISION_BLOCKERS = frozenset(
    {
        "NO_OWNER_DECISION_RECORD",
        "ALL_DECISION_RECORDS_STALE",
        "ALL_CURRENT_DECISIONS_REVOKED",
    }
)
_CONFLICT_BLOCKERS = frozenset({"DECISIONS_AMBIGUOUS", "DECISIONS_CONFLICTING"})
_AUTHORITY_BLOCKER_PREFIXES = (
    "OWNER_AUTHORITY_",
    "OWNER_REVOCATION_",
    "LIFECYCLE_",
)

# Structural integrity checks whose joint success means "the published
# bytes and identities are machine-verified" for this pair.
_PUBLISHED_INTEGRITY_CHECKS = (
    "RELEASE_MANIFEST_VALID",
    "BASE_PROFILE_BYTES_HASH",
    "TARGET_PROFILE_BYTES_HASH",
    "TARGET_PROFILE_IDENTITY",
)


class ReadinessReplayInputsV1(BaseModel):
    """Bounded read-only provenance of the explicitly supplied CLI path inputs.

    Passed by the CLI handler so retry/preview hints can quote the exact
    effective file-path arguments — repeatable options keep their per-option
    order and multiplicity.  This is hint provenance only: it never feeds
    any identity, verification, authorization or persistence path, it is
    never included in the persisted summary contract, and it never carries
    secret material (only operator-supplied path references the hints would
    need anyway).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["readiness_replay_inputs_v1"] = "readiness_replay_inputs_v1"
    decision_records: tuple[Annotated[StrictStr, Field(max_length=2_048)], ...] = (
        Field(default=(), max_length=32)
    )
    revocations: tuple[Annotated[StrictStr, Field(max_length=2_048)], ...] = (
        Field(default=(), max_length=32)
    )
    policy_exceptions: tuple[Annotated[StrictStr, Field(max_length=2_048)], ...] = (
        Field(default=(), max_length=32)
    )
    signed_revocations: tuple[Annotated[StrictStr, Field(max_length=2_048)], ...] = (
        Field(default=(), max_length=32)
    )
    signed_supersessions: tuple[Annotated[StrictStr, Field(max_length=2_048)], ...] = (
        Field(default=(), max_length=32)
    )
    trust_root: StrictStr | None = Field(
        default=None, min_length=1, max_length=2_048
    )
    authority_evidence: StrictStr | None = Field(
        default=None, min_length=1, max_length=2_048
    )
    boundary_input: StrictStr | None = Field(
        default=None, min_length=1, max_length=2_048
    )


class OwnerReadinessSummaryV1(BaseModel):
    """The immutable, informational owner-readiness projection.

    Fixed literals make the boundary explicit: this summary never approves,
    authorizes or executes anything, and it is not an authorization bearer.
    A READY plan observed here is a *fact about a fresh plan derivation*,
    not a permission; the apply boundary re-derives everything under its
    own locks and expected hashes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_readiness_summary_v1"] = "owner_readiness_summary_v1"
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    summary_id: StrictStr = Field(min_length=1)

    # --- published pair (fresh C1 audit facts) ---
    base_profile_id: StrictStr = Field(min_length=1, max_length=128)
    base_profile_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    target_profile_id: StrictStr = Field(min_length=1, max_length=128)
    target_profile_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    release_manifest_id: StrictStr = Field(min_length=1)
    release_manifest_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    audit_id: StrictStr = Field(min_length=1)
    audit_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    audit_activation_readiness: StrictStr = Field(min_length=1, max_length=64)
    published_bytes_verified: StrictBool
    uncovered_policy_findings: list[StrictStr] = Field(max_length=64)
    policy_question_zh: list[StrictStr] = Field(min_length=1, max_length=32)
    behavior_contrast_zh: list[StrictStr] = Field(min_length=1, max_length=32)

    # --- owner decision / authority (fresh C2-R1 plan facts) ---
    decision_authority_state: StrictStr | None = Field(
        default=None, min_length=1, max_length=64
    )
    decision_record_id: StrictStr | None = Field(default=None, min_length=1)
    decision: Literal["ACCEPT_WITH_EXCEPTION", "REJECT"] | None = None
    owner_authority_revalidated: StrictBool
    plan_state: StrictStr | None = Field(
        default=None, min_length=1, max_length=64
    )
    plan_blockers: list[StrictStr] = Field(max_length=256)

    # --- observed project config ---
    project_config_path: StrictStr = Field(min_length=1, max_length=2_048)
    project_config_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    current_default_profile: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )

    # --- activation store (unchanged C4-B projection, when supplied) ---
    activation_root_supplied: StrictBool
    activation_store_status: StrictStr | None = Field(
        default=None, min_length=1, max_length=64
    )
    activation_store_problems: list[StrictStr] = Field(max_length=256)
    activation_store_guidance_zh: list[StrictStr] = Field(max_length=64)

    # --- the derived journey view ---
    journey_state: Literal[
        "OWNER_DECISION_REQUIRED",
        "REJECTED_BY_OWNER",
        "DECISION_CONFLICT",
        "OWNER_AUTHORITY_NOT_PROVEN",
        "PUBLISHED_PAIR_BLOCKED",
        "ACTIVATION_BLOCKED",
        "RECOVERY_PENDING",
        "STORE_NEEDS_ATTENTION",
        "ALREADY_APPLIED",
        "ROLLED_BACK",
        "PREVIEW_READY",
    ]
    informational_blockers: list[StrictStr] = Field(max_length=256)
    next_steps_zh: list[StrictStr] = Field(min_length=1, max_length=16)

    # --- fixed informational-only boundary literals ---
    requires_human_policy_approval: Literal[True] = True
    automatic_activation_allowed: Literal[False] = False
    execution_performed: Literal[False] = False
    summary_is_informational_not_authorization: Literal[True] = True
    read_only_observation: Literal[True] = True

    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.journey_state not in JOURNEY_STATE_VALUES:
            raise ValueError(
                f"unknown journey state: {self.journey_state}"
            )
        # A READY plan observed by an informational summary never carries
        # authority claims of its own.
        if self.journey_state == "PREVIEW_READY" and self.plan_blockers:
            raise ValueError("a preview-ready journey carries no plan blockers")
        if self.owner_authority_revalidated and self.decision != "ACCEPT_WITH_EXCEPTION":
            raise ValueError(
                "authority re-attestation is only claimed for an accepted decision"
            )
        if not self.activation_root_supplied and (
            self.activation_store_status is not None
            or self.activation_store_problems
            or self.activation_store_guidance_zh
        ):
            raise ValueError("store facts require a supplied activation root")
        payload = self.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("summary content_sha256 does not match content")
        return self


# ---------------------------------------------------------------------------
# Chinese composition helpers (deterministic over derived facts only)
# ---------------------------------------------------------------------------


def _policy_question_lines(
    audit: ProfileSemanticAuditV1, target_profile: object
) -> list[str]:
    """Explain the uncovered semantic findings with derived thresholds."""

    uncovered = sorted(audit.policy_decision_reasons)
    if not uncovered:
        return [
            "当前配对没有未覆盖的语义政策发现：门槛与档位关系全部满足规范，"
            "仍需所有者就启用本身做出人类决策。"
        ]
    lines: list[str] = []
    bands = getattr(getattr(target_profile, "cdc", None), "yield_bands", None)
    gate = getattr(bands, "pass_", None) if bands is not None else None
    s_band = getattr(bands, "s", None) if bands is not None else None
    tiers = getattr(getattr(target_profile, "valuation", None), "tiers", None)
    extreme = (
        tiers.get("extreme_safety") if isinstance(tiers, dict) else None
    )
    extreme_yield = getattr(extreme, "cdc_yield", None)
    target_id = audit.target_profile_id
    if gate is not None and s_band is not None:
        lines.append(
            f"{target_id} 的 CDC 通过门槛为 {gate:.0%}（{gate}），而其 S 档仍为 "
            f"{s_band:.0%}（{s_band}）：通过门槛高于自家 S 档"
            "（CDC_BAND_ORDER_VIOLATION）——落在 S 档与门槛之间的收益率满足较高"
            "诊断档位，却会被资格门槛拦下。"
        )
    if gate is not None and extreme_yield is not None:
        lines.append(
            f"同一 {gate:.0%} 门槛也高于 extreme_safety 估值档的 CDC 门槛 "
            f"{extreme_yield:.0%}（{extreme_yield}）"
            "（CDC_GATE_TIER_COHERENCE_VIOLATION）——满足最高估值档的收益率仍"
            "可能被资格门槛压到 WATCH，估值被扣留。"
        )
    if len(lines) < len(uncovered):
        for reason in uncovered:
            if reason.split(":", 1)[0] not in (
                "CDC_BAND_ORDER_VIOLATION",
                "CDC_GATE_TIER_COHERENCE_VIOLATION",
            ):
                lines.append(f"未覆盖的政策发现：{reason}。")
    lines.append(
        "这是所有者本人的经济政策决策：接受需要声明覆盖上述发现的版本化策略"
        "例外，拒绝则保持默认档案不变；发布、CI 成功与本摘要都不是批准。"
    )
    return lines


def _behavior_contrast_lines(audit: ProfileSemanticAuditV1) -> list[str]:
    """The first diverging behavioural row from the real engine replay."""

    changed = sorted(
        (row for row in audit.pipeline_boundary_rows if row.decision_changed),
        key=lambda row: row.target_cdc_yield,
    )
    if not changed:
        return [
            "边界回放中两条档案在所有探针上的决策一致：本次发布不会改变任何"
            "边界收益率下的最终决策。"
        ]
    row = changed[0]
    gate_diverging = [
        item
        for item in audit.gate_boundary_rows
        if item.diverges
    ]
    window_hint = ""
    if gate_diverging:
        low = min(item.cdc_yield for item in gate_diverging)
        high = max(item.cdc_yield for item in gate_diverging)
        window_hint = f"门槛分歧区间约 [{low:.0%}, {high:.2%}]。"
    return [
        f"以 {row.target_cdc_yield:.1%} 收益率对照（真实引擎回放，分歧区间内第"
        "一个行为不同的收益率）："
        f"{audit.base_profile_id} 判门槛 {row.base_gate_status}、估值 "
        f"{row.base_valuation_state}、决策 {row.base_decision_state}；"
        f"{audit.target_profile_id} 判门槛 {row.target_gate_status}、估值 "
        f"{row.target_valuation_state}、决策 {row.target_decision_state}。"
        f"{window_hint}"
        f"门槛分歧行 {audit.gate_divergence_count} 个，决策变化行 "
        f"{audit.decision_divergence_count} 个。"
    ]


# ---------------------------------------------------------------------------
# Journey derivation
# ---------------------------------------------------------------------------


def _derive_journey_state(
    *,
    audit: ProfileSemanticAuditV1,
    plan: ProfileActivationPlanV1,
    store_status: str | None,
) -> str:
    if store_status in _PENDING_STORE_STATUSES:
        return "RECOVERY_PENDING"
    if store_status in _ATTENTION_STORE_STATUSES:
        return "STORE_NEEDS_ATTENTION"
    if store_status == "ACTIVATED_VERIFIED":
        return "ALREADY_APPLIED"
    if store_status == "ROLLED_BACK_VERIFIED":
        return "ROLLED_BACK"
    if audit.activation_readiness == "BLOCKED_FOR_ACTIVATION":
        return "PUBLISHED_PAIR_BLOCKED"
    blockers = set(plan.blockers)
    if blockers & _NO_DECISION_BLOCKERS:
        return "OWNER_DECISION_REQUIRED"
    if "DECISION_IS_REJECT" in blockers:
        return "REJECTED_BY_OWNER"
    if blockers & _CONFLICT_BLOCKERS:
        return "DECISION_CONFLICT"
    if any(
        blocker.startswith(_AUTHORITY_BLOCKER_PREFIXES)
        for blocker in blockers
    ):
        return "OWNER_AUTHORITY_NOT_PROVEN"
    if plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION":
        return "PREVIEW_READY"
    return "ACTIVATION_BLOCKED"


def _informational_blockers(
    journey_state: str,
    audit: ProfileSemanticAuditV1,
    plan: ProfileActivationPlanV1,
) -> list[str]:
    if journey_state == "OWNER_DECISION_REQUIRED":
        blockers = {"OWNER_DECISION_REQUIRED"}
    elif journey_state == "OWNER_AUTHORITY_NOT_PROVEN":
        blockers = {"OWNER_AUTHORITY_NOT_PROVEN"}
    elif journey_state == "DECISION_CONFLICT":
        blockers = {"DECISION_CONFLICT"}
    elif journey_state == "PUBLISHED_PAIR_BLOCKED":
        blockers = set(audit.blocking_checks)
    elif journey_state == "ACTIVATION_BLOCKED":
        blockers = set()
    else:
        # Terminal, applied, rolled back, recovery and preview-ready states
        # name their facts in their own sections, not as blockers.
        blockers = set()
    blockers.update(plan.blockers)
    if journey_state != "PREVIEW_READY":
        blockers.update(audit.policy_decision_reasons)
    return sorted(blockers)


def _quoted(*argv: str) -> str:
    """One complete command line from its exact argument vector."""

    return shlex.join(["tve", *argv])


def _replay_argv(
    *,
    base: str,
    target: str,
    manifest: str,
    config: str,
    activation_root: Path | None,
    replay: ReadinessReplayInputsV1,
) -> list[str]:
    """The readiness-summary retry argument vector carrying every explicitly
    supplied input (per-option order and multiplicity preserved).

    A command that silently dropped supplied decision context would reset an
    authenticated journey to the journey-start view, so every non-empty
    replay field is quoted into the retry exactly as supplied; absent
    options contribute nothing.
    """

    argv = [
        "evolution",
        "readiness-summary",
        "--base-profile",
        base,
        "--target-profile",
        target,
        "--release-manifest",
        manifest,
        "--project-config",
        config,
    ]
    if replay.boundary_input is not None:
        argv.extend(["--boundary-input", replay.boundary_input])
    for path in replay.decision_records:
        argv.extend(["--decision-record", path])
    for path in replay.revocations:
        argv.extend(["--revocation", path])
    for path in replay.policy_exceptions:
        argv.extend(["--policy-exception", path])
    if replay.trust_root is not None:
        argv.extend(["--trust-root", replay.trust_root])
    if replay.authority_evidence is not None:
        argv.extend(["--authority-evidence", replay.authority_evidence])
    for path in replay.signed_revocations:
        argv.extend(["--signed-revocation", path])
    for path in replay.signed_supersessions:
        argv.extend(["--signed-supersession", path])
    if activation_root is not None:
        argv.extend(["--activation-root", str(activation_root)])
    return argv


def _preview_argv(
    *,
    base: str,
    target: str,
    manifest: str,
    config: str,
    activation_root: Path,
    replay: ReadinessReplayInputsV1,
) -> list[str] | None:
    """The read-only activate-profile preview argument vector, or None.

    The preview parser requires ``--decision-record`` and
    ``--activation-root``; a preview advertised as replaying the observed
    verified journey must also carry the exception/trust/evidence inputs.
    When any of those is unknown the caller must stay prose — an incomplete
    command displayed as runnable is exactly the F1/F2 defect class.
    """

    if not replay.decision_records:
        return None
    argv = [
        "evolution",
        "activate-profile",
        "--base-profile",
        base,
        "--target-profile",
        target,
        "--release-manifest",
        manifest,
    ]
    if replay.boundary_input is not None:
        argv.extend(["--boundary-input", replay.boundary_input])
    for path in replay.decision_records:
        argv.extend(["--decision-record", path])
    for path in replay.revocations:
        argv.extend(["--revocation", path])
    for path in replay.policy_exceptions:
        argv.extend(["--policy-exception", path])
    argv.extend(["--project-config", config])
    if replay.trust_root is not None:
        argv.extend(["--trust-root", replay.trust_root])
    if replay.authority_evidence is not None:
        argv.extend(["--authority-evidence", replay.authority_evidence])
    for path in replay.signed_revocations:
        argv.extend(["--signed-revocation", path])
    for path in replay.signed_supersessions:
        argv.extend(["--signed-supersession", path])
    argv.extend(["--activation-root", str(activation_root)])
    return argv


def _next_steps_zh(
    *,
    journey_state: str,
    base_profile_path: Path,
    target_profile_path: Path,
    release_manifest_path: Path,
    project_config_path: Path,
    activation_root: Path | None,
    base_profile_id: str,
    target_profile_id: str,
    replay_inputs: ReadinessReplayInputsV1 | None,
) -> list[str]:
    base = str(base_profile_path)
    target = str(target_profile_path)
    manifest = str(release_manifest_path)
    config = str(project_config_path)

    if replay_inputs is not None:
        retry_command = _quoted(
            *_replay_argv(
                base=base,
                target=target,
                manifest=manifest,
                config=config,
                activation_root=activation_root,
                replay=replay_inputs,
            )
        )
    else:
        retry_command = None
    retry_step = (
        f"重新运行本命令复核（零写入，输入逐项原样保留）：{retry_command}。"
        if retry_command is not None
        else (
            "重新运行 tve evolution readiness-summary 复核时，请原样保留本次提供的"
            "全部输入（--decision-record/--policy-exception/--trust-root/"
            "--authority-evidence/--boundary-input/--activation-root 等，可重复项"
            "保持顺序与次数）；缺项会使观察退回旅程起点视图。"
        )
    )
    status_command = (
        _quoted(
            "evolution",
            "activation-status",
            "--project-config",
            config,
            "--activation-root",
            str(activation_root),
        )
        if activation_root is not None
        else None
    )
    status_step = (
        f"用只读状态检查复核（零写入）：{status_command}。"
        if status_command is not None
        else (
            "只读状态检查 activation-status 需要 --activation-root 与 "
            "--project-config 两个必填路径。"
        )
    )
    preview_command = (
        _quoted(
            *_preview_argv(
                base=base,
                target=target,
                manifest=manifest,
                config=config,
                activation_root=activation_root,
                replay=replay_inputs,
            )
        )
        if replay_inputs is not None
        and activation_root is not None
        and replay_inputs.decision_records
        else None
    )
    # decision-dossier / plan-activation REQUIRE an operator-chosen --output
    # and persist a file: prose with the write disclosed, never a paste-ready
    # command (an unknown output path is not real input).
    dossier_step = (
        "生成决策材料（该步骤会写入你显式选择的 Markdown 文件，是旅程中唯一写"
        f"文件步骤）：运行 tve evolution decision-dossier，传入 --base-profile "
        f"{shlex.quote(base)} --target-profile {shlex.quote(target)} "
        f"--release-manifest {shlex.quote(manifest)}，再显式加上 --output 与你"
        "选择的输出路径。"
    )
    if retry_command is not None:
        plan_activation_step = (
            "如需导出完整计划文件，可运行 tve evolution plan-activation：传入与"
            "上述重放命令完全相同的输入，并额外显式选择 --output 输出路径；该命令"
            "会写入该计划文件（写文件命令，非零写入检查）。"
        )
    else:
        plan_activation_step = (
            "如需导出完整计划文件，可运行 tve evolution plan-activation：传入与本"
            "次 readiness-summary 完全相同的全部输入（决策记录、策略例外、信任根、"
            "证据等，可重复项保持顺序与次数），并额外显式选择 --output 输出路径；"
            "该命令会写入该计划文件（写文件命令，非零写入检查）。"
        )

    if journey_state == "OWNER_DECISION_REQUIRED":
        return [
            dossier_step,
            "阅读上方政策问题（通过门槛与 S 档/估值档关系）及行为对照，独立做出 "
            "ACCEPT/REJECT 决策；按 owner-provenance-walkthrough.md 用你自己的"
            "密钥签名并 record-decision 记录（人工步骤，不可自动化）。",
            retry_step,
            "状态就绪后以 activate-profile 默认预览核对该次计划（预览只读、"
            "零写入）。",
        ]
    if journey_state == "REJECTED_BY_OWNER":
        return [
            f"所有者已拒绝：{target_profile_id} 保持已发布但不启用，默认档案保持 "
            f"{base_profile_id}，无需任何操作。",
            "如需启用，需要一个新的所有者决策：重新运行 tve evolution "
            f"decision-dossier（传入 --base-profile {shlex.quote(base)} "
            f"--target-profile {shlex.quote(target)} --release-manifest "
            f"{shlex.quote(manifest)}，并显式选择 --output 输出路径；该命令会写入"
            "你选择的 Markdown 文件）。",
            retry_step,
        ]
    if journey_state == "DECISION_CONFLICT":
        return [
            "存在互相冲突的决策记录（例如同时有 ACCEPT 与 REJECT）：请以签名撤销/"
            "取代（owner-lifecycle）澄清后重试；在此之前任何启用都被阻塞。",
            f"澄清后重新运行本命令核对：{retry_command}。" if retry_command else retry_step,
        ]
    if journey_state == "OWNER_AUTHORITY_NOT_PROVEN":
        return [
            "决策记录存在但其授权未获当前信任根的全新验证（缺少 --trust-root/"
            "--authority-evidence、密钥被撤销/轮换或证据过期）：以当前信任根重新"
            "捕获证据，或重新签名记录。",
            f"修正后重新运行本命令核对 plan_blockers 是否清空：{retry_command}。"
            if retry_command
            else retry_step,
        ]
    if journey_state == "PUBLISHED_PAIR_BLOCKED":
        return [
            "发布配对未通过结构校验（字节哈希、身份或清单校验失败）：请勿启用；"
            "核对文件字节后重新运行只读审计命令 tve evolution audit-profile 定位"
            "具体检查。",
            f"修复来源后重新运行本命令：{retry_command}。" if retry_command else retry_step,
        ]
    if journey_state == "ACTIVATION_BLOCKED":
        return [
            "计划仍被阻塞（见 plan_blockers，如绑定过期、例外缺失、配置已是目标"
            "等）：逐项处理命名阻塞项。",
            plan_activation_step,
            f"或重跑本命令：{retry_command}。" if retry_command else retry_step,
        ]
    if journey_state == "RECOVERY_PENDING":
        assert status_command is not None  # store facts require a root
        return [
            "存在中断的激活/回滚步骤：先用只读状态检查确认具体阶段："
            f"{status_command}。",
            "按其指引重新执行同一 apply/rollback 命令即可确定性补齐（不会重复"
            "改写配置）；本摘要不会替你执行任何恢复。",
        ]
    if journey_state == "STORE_NEEDS_ATTENTION":
        assert status_command is not None  # store facts require a root
        return [
            "激活存储存在分歧、歧义或损坏条目（见 activation_store_problems）："
            "逐项人工核对（比对 before-images/ 备份），本命令不修复。",
            f"先运行只读状态检查定位：{status_command}。",
        ]
    if journey_state == "ALREADY_APPLIED":
        return [
            "当前配置已是目标档案且有已验证的激活记录；如需恢复默认，执行回执"
            "绑定的 rollback-activation 命令（见回执或 activation-status 指引）。",
            status_step,
        ]
    if journey_state == "ROLLED_BACK":
        return [
            "激活已被回滚并字节验证；当前默认档案为变更前档案，无需处理。",
            "如需再次启用，需要一个新的所有者决策与新的预览（见 "
            "profile-activation-executor.md 第 4 节；新决策就绪后用 activate-profile "
            "默认预览核对，只读、不带 --apply）。",
            status_step,
        ]
    # PREVIEW_READY
    steps = []
    if preview_command is not None:
        steps.append(
            "运行只读预览（零写入），核对唯一变更行、plan_id 与 "
            f"original_config_sha256：{preview_command}。"
        )
    else:
        steps.append(
            "运行只读预览前请补齐 activate-profile 的输入：--decision-record 与 "
            "--activation-root 为必填，并请原样保留本次的 --policy-exception/"
            "--trust-root/--authority-evidence 等输入（预览默认只读、零写入）。"
        )
    steps.append(
        "仅在你明确决定执行时，逐字复制预览输出的 apply_command_hint 执行"
        "（含 --expected-plan-id 与 --expected-config-sha256）；执行与回滚是"
        "所有者的显式操作，本摘要不构成授权。"
    )
    steps.append(status_step)
    steps.append(retry_step)
    return steps


# ---------------------------------------------------------------------------
# The summary boundary
# ---------------------------------------------------------------------------


def summarize_owner_readiness(
    *,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    project_config_path: str | Path,
    boundary_input=None,
    decision_records: Sequence = (),
    revocations: Sequence = (),
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
    authority_verifier=None,
    authority_evidence=None,
    signed_revocations: Sequence = (),
    signed_supersessions: Sequence = (),
    lifecycle_trust_root=None,
    activation_root: str | Path | None = None,
    replay_inputs: ReadinessReplayInputsV1 | None = None,
) -> OwnerReadinessSummaryV1:
    """Derive the single read-only readiness summary; performs zero writes.

    Reuses exactly the established verification paths: a fresh C1 semantic
    audit, a fresh C2-R1 activation plan (whose re-attestation is the only
    source for ``owner_authority_revalidated``) and, when an activation
    root is supplied, the unchanged C4-B store classification.  Nothing is
    locked, created, signed, approved, applied, repaired or persisted; a
    missing activation store stays missing.

    ``replay_inputs`` is the CLI handler's bounded read-only provenance of
    the explicitly supplied path options; it feeds ONLY the next-step hint
    text.  Without it no retry/preview command is displayed at all (a
    library caller lacks the CLI argument provenance a faithful replay
    would need), and the steps stay prose.
    """

    base_path = Path(base_profile_path)
    target_path = Path(target_profile_path)
    manifest_path = Path(release_manifest_path)
    config_path = Path(project_config_path)
    root_path = Path(activation_root) if activation_root is not None else None

    audit = audit_profile_semantics(
        base_profile_path=base_path,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=boundary_input,
        policy_exceptions=policy_exceptions,
    )
    plan = plan_profile_activation(
        base_profile_path=base_path,
        target_profile_path=target_path,
        release_manifest_path=manifest_path,
        boundary_input=boundary_input,
        decision_records=decision_records,
        revocations=revocations,
        policy_exceptions=policy_exceptions,
        authority_verifier=authority_verifier,
        signed_revocations=signed_revocations,
        signed_supersessions=signed_supersessions,
        lifecycle_trust_root=lifecycle_trust_root,
        project_config_path=config_path,
    )
    store: ProfileActivationStatusV1 | None = None
    if root_path is not None:
        store = inspect_activation_status(
            activation_root=root_path,
            project_config_path=config_path,
        )

    # The observed config facts come from the established parsers only.
    config_sha = store.current_config_sha256 if store is not None else (
        plan.rollback.prior_project_config_sha256
    )
    current_default = (
        store.current_default_profile if store is not None
        else plan.rollback.prior_default_profile
    )
    if config_sha is None:
        # Unreachable through the CLI (the config guard runs first); the
        # library keeps the projection honest instead of inventing bytes.
        raise ValueError(
            "the project config could not be observed read-only; supply an "
            "existing regular file"
        )

    # The getattr-based defensive access keeps an unparseable target (the
    # audit already reports BLOCKED_FOR_ACTIVATION) from inventing numbers.
    target_rule_profile, _ = _parse_profile(target_path.read_bytes())
    journey_state = _derive_journey_state(
        audit=audit, plan=plan, store_status=store.status if store else None
    )
    summary_id = deterministic_id(
        "owner-readiness-summary",
        audit.base_profile_id,
        audit.base_profile_sha256,
        audit.target_profile_id,
        audit.target_profile_sha256,
        audit.release_manifest_id,
        audit.release_manifest_content_sha256,
        plan.plan_id,
        plan.content_sha256,
        store.status if store is not None else "",
        config_sha,
        journey_state,
    )
    payload = {
        "contract": "owner_readiness_summary_v1",
        "schema_version": "1.0.0",
        "summary_id": summary_id,
        "base_profile_id": audit.base_profile_id,
        "base_profile_sha256": audit.base_profile_sha256,
        "target_profile_id": audit.target_profile_id,
        "target_profile_sha256": audit.target_profile_sha256,
        "release_manifest_id": audit.release_manifest_id,
        "release_manifest_content_sha256": audit.release_manifest_content_sha256,
        "audit_id": audit.audit_id,
        "audit_content_sha256": audit.content_sha256,
        "audit_activation_readiness": audit.activation_readiness,
        "published_bytes_verified": all(
            check.status == "PASS"
            for check in audit.checks
            if check.name in _PUBLISHED_INTEGRITY_CHECKS
        )
        and audit.activation_readiness != "BLOCKED_FOR_ACTIVATION",
        "uncovered_policy_findings": sorted(audit.policy_decision_reasons),
        "policy_question_zh": _policy_question_lines(audit, target_rule_profile),
        "behavior_contrast_zh": _behavior_contrast_lines(audit),
        "decision_authority_state": plan.decision_authority_state,
        "decision_record_id": plan.decision_record_id,
        "decision": plan.decision,
        "owner_authority_revalidated": (
            plan.authority_reverification_status == "REVERIFIED"
        ),
        "plan_state": plan.plan_state,
        "plan_blockers": sorted(plan.blockers),
        "project_config_path": str(config_path),
        "project_config_sha256": config_sha,
        "current_default_profile": current_default,
        "activation_root_supplied": root_path is not None,
        "activation_store_status": store.status if store is not None else None,
        "activation_store_problems": list(store.problems) if store else [],
        "activation_store_guidance_zh": list(store.guidance_zh) if store else [],
        "journey_state": journey_state,
        "informational_blockers": _informational_blockers(journey_state, audit, plan),
        "next_steps_zh": _next_steps_zh(
            journey_state=journey_state,
            base_profile_path=base_path,
            target_profile_path=target_path,
            release_manifest_path=manifest_path,
            project_config_path=config_path,
            activation_root=root_path,
            base_profile_id=audit.base_profile_id,
            target_profile_id=audit.target_profile_id,
            replay_inputs=replay_inputs,
        ),
        "requires_human_policy_approval": True,
        "automatic_activation_allowed": False,
        "execution_performed": False,
        "summary_is_informational_not_authorization": True,
        "read_only_observation": True,
    }
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return OwnerReadinessSummaryV1.model_validate(payload)


__all__ = [
    "JOURNEY_STATE_VALUES",
    "OwnerReadinessSummaryV1",
    "ReadinessReplayInputsV1",
    "summarize_owner_readiness",
]
