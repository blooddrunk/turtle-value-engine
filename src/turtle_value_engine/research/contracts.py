"""Model-neutral, persisted contracts for bounded research runs.

The models in this module are deliberately separate from the deterministic
engine's ``CompanyAnalysis`` contracts.  An analyst can only return typed
claims, references to evidence present in a packet, unresolved questions and
PROPOSED adjustments.  The deterministic calculator and the existing
adjustment materialization boundary remain the only places where those
proposals can affect an analysis.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from turtle_value_engine.models import (
    Adjustment,
    BusinessQuality,
    BusinessQualityDimension,
    ConfidenceLevel,
    Evidence,
    Fact,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

RESEARCH_CONTRACT_VERSION = "research-v1"
RESEARCH_PROTOCOL_VERSION = "research-protocol-v1"
RESEARCH_PROMPT_VERSION = "research-prompt-v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_BUSINESS_QUALITY_DIMENSION_ORDER = (
    "demand_durability",
    "cyclicality",
    "pricing_power",
    "moat",
    "capital_efficiency",
    "dependency",
    "regulatory_risk",
    "predictability",
)


class AnalystRole(StrEnum):
    """Stable role names understood by external agent runtimes."""

    RESEARCH = "RESEARCH"
    QUALITY_ANALYST = "QUALITY_ANALYST"
    SKEPTIC = "SKEPTIC"
    ADJUDICATOR = "ADJUDICATOR"
    REPORT_COMPOSER = "REPORT_COMPOSER"


class ResearchIntent(StrEnum):
    """The bounded purpose of one research packet."""

    THESIS = "THESIS"
    FALSIFICATION = "FALSIFICATION"
    ADJUDICATION = "ADJUDICATION"


class AnalystExecutionMode(StrEnum):
    """Whether a run came from a frozen client or an external model runtime."""

    SCRIPTED = "SCRIPTED"
    EXTERNAL = "EXTERNAL"
    LIVE = "LIVE"


class AnalystRunStatus(StrEnum):
    """Persisted terminal states for analyst calls."""

    COMPLETED = "COMPLETED"


BusinessQualityDimensionName: TypeAlias = Literal[
    "demand_durability",
    "cyclicality",
    "pricing_power",
    "moat",
    "capital_efficiency",
    "dependency",
    "regulatory_risk",
    "predictability",
]


def _unique(values: list[str]) -> list[str]:
    """Validate a stable list without silently deduplicating model output."""

    if len(values) != len(set(values)):
        raise ValueError("values must not contain duplicates")
    return values


def _hash_payload(model: BaseModel, *excluded: str) -> str:
    payload = model.model_dump(mode="json", exclude=set(excluded))
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class ResearchQuestion(BaseModel):
    """One exact, bounded research question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(min_length=1)
    dimension: BusinessQualityDimensionName | None = None
    intent: ResearchIntent
    text: StrictStr = Field(min_length=1, max_length=2_000)
    focus_areas: list[StrictStr] = Field(default_factory=list, max_length=16)
    required: StrictBool = True

    @property
    def question_id(self) -> str:
        """Compatibility vocabulary for callers that call this a question ID."""

        return self.id

    @field_validator("focus_areas")
    @classmethod
    def validate_focus_areas(cls, value: list[str]) -> list[str]:
        return _unique(value)


class PacketFact(BaseModel):
    """A source fact exposed to an analyst without presenting it as a metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: StrictStr = Field(min_length=1)
    field: StrictStr = Field(min_length=1)
    value: int | float | str | bool | None
    unit: StrictStr | None = None
    currency: StrictStr | None = Field(default=None, min_length=3, max_length=3)
    period: StrictStr = Field(min_length=1)
    source_evidence_ids: list[StrictStr] = Field(min_length=1)
    confidence: StrictFloat = Field(ge=0, le=1)
    origin: Literal["NORMALIZED_SOURCE_FACT", "EFFECTIVE_INPUT_FACT"] = "NORMALIZED_SOURCE_FACT"
    source_fact_id: StrictStr | None = Field(default=None, min_length=1)
    applied_adjustment_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("source_evidence_ids", "applied_adjustment_ids")
    @classmethod
    def validate_unique_references(cls, value: list[str]) -> list[str]:
        return _unique(value)

    @classmethod
    def from_fact(cls, fact: Fact) -> PacketFact:
        return cls(
            fact_id=fact.id,
            field=fact.field,
            value=fact.value,
            unit=fact.unit,
            currency=fact.currency,
            period=fact.period,
            source_evidence_ids=list(fact.source_evidence_ids),
            confidence=fact.confidence,
            origin=(
                "EFFECTIVE_INPUT_FACT"
                if fact.source_fact_id is not None
                else "NORMALIZED_SOURCE_FACT"
            ),
            source_fact_id=fact.source_fact_id,
            applied_adjustment_ids=list(fact.applied_adjustment_ids),
        )


class DeterministicMetric(BaseModel):
    """A read-only metric already produced by deterministic engine code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    value: StrictFloat | None = None
    unit: StrictStr | None = None
    period: StrictStr | None = None
    calculation_contract: Literal["DETERMINISTIC_ENGINE"] = "DETERMINISTIC_ENGINE"
    source_evidence_ids: list[StrictStr] = Field(default_factory=list)

    @field_validator("source_evidence_ids")
    @classmethod
    def validate_unique_evidence_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)


class EvidencePacket(BaseModel):
    """The complete bounded input made available to one analyst task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["evidence_packet_v1"] = "evidence_packet_v1"
    packet_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    role: AnalystRole
    question: ResearchQuestion
    intent: ResearchIntent
    evidence: list[Evidence] = Field(max_length=128)
    facts: list[PacketFact] = Field(max_length=256)
    deterministic_metrics: list[DeterministicMetric] = Field(max_length=128)
    available_evidence_ids: list[StrictStr] = Field(default_factory=list)
    available_fact_ids: list[StrictStr] = Field(default_factory=list)
    undated_evidence_ids: list[StrictStr] = Field(default_factory=list)
    protocol_version: StrictStr = Field(default=RESEARCH_PROTOCOL_VERSION, min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator(
        "available_evidence_ids",
        "available_fact_ids",
        "undated_evidence_ids",
    )
    @classmethod
    def validate_unique_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)

    @model_validator(mode="after")
    def validate_packet_identity(self) -> Self:
        evidence_ids = [item.id for item in self.evidence]
        fact_ids = [item.fact_id for item in self.facts]
        metric_ids = [item.id for item in self.deterministic_metrics]
        if self.available_evidence_ids != evidence_ids:
            raise ValueError("available_evidence_ids must preserve packet evidence order")
        if self.available_fact_ids != fact_ids:
            raise ValueError("available_fact_ids must preserve packet fact order")
        if not set(self.undated_evidence_ids).issubset(evidence_ids):
            raise ValueError("undated_evidence_ids must refer to packet evidence")
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("deterministic metric IDs must be unique")
        expected = _hash_payload(self, "content_sha256")
        if self.content_sha256 != expected:
            raise ValueError("evidence packet content_sha256 does not match packet content")
        if self.question.intent is not self.intent:
            raise ValueError("packet intent must match question intent")
        return self

    @classmethod
    def build(
        cls,
        *,
        analysis_id: str,
        listing_id: str,
        as_of: date,
        profile_id: str,
        role: AnalystRole,
        question: ResearchQuestion,
        evidence: list[Evidence],
        facts: list[PacketFact],
        deterministic_metrics: list[DeterministicMetric],
        undated_evidence_ids: list[str] | None = None,
        protocol_version: str = RESEARCH_PROTOCOL_VERSION,
    ) -> EvidencePacket:
        """Construct a packet and derive its content identity canonically."""

        evidence_ids = [item.id for item in evidence]
        fact_ids = [item.fact_id for item in facts]
        payload = {
            "contract": "evidence_packet_v1",
            "packet_id": "pending",
            "analysis_id": analysis_id,
            "listing_id": listing_id,
            "as_of": as_of.isoformat(),
            "profile_id": profile_id,
            "role": role.value,
            "question": question.model_dump(mode="json"),
            "intent": question.intent.value,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "facts": [item.model_dump(mode="json") for item in facts],
            "deterministic_metrics": [
                item.model_dump(mode="json") for item in deterministic_metrics
            ],
            "available_evidence_ids": evidence_ids,
            "available_fact_ids": fact_ids,
            "undated_evidence_ids": undated_evidence_ids or [],
            "protocol_version": protocol_version,
        }
        content_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        packet_id = deterministic_id(
            "evidence-packet",
            analysis_id,
            listing_id,
            as_of.isoformat(),
            profile_id,
            role.value,
            question.id,
            question.intent.value,
            evidence_ids,
            fact_ids,
            [item.id for item in deterministic_metrics],
        )
        payload["packet_id"] = packet_id
        # The packet hash intentionally includes the deterministic packet ID;
        # the persisted identity is therefore self-contained.
        content_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        payload["content_sha256"] = content_sha256
        return cls.model_validate(payload)

    @property
    def evidence_by_id(self) -> dict[str, Evidence]:
        return {item.id: item for item in self.evidence}

    @property
    def metric_ids(self) -> set[str]:
        return {item.id for item in self.deterministic_metrics}


class EvidenceClaim(BaseModel):
    """A supporting claim whose evidence must be in the task packet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(min_length=1)
    direction: Literal["SUPPORT"] = "SUPPORT"
    statement: StrictStr = Field(min_length=1, max_length=4_000)
    evidence_ids: list[StrictStr] = Field(min_length=1, max_length=32)
    deterministic_metric_ids: list[StrictStr] = Field(default_factory=list, max_length=32)
    confidence: StrictFloat = Field(ge=0, le=1)

    @property
    def claim_id(self) -> str:
        return self.id

    @field_validator("evidence_ids", "deterministic_metric_ids")
    @classmethod
    def validate_unique_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)


class CounterEvidenceClaim(BaseModel):
    """A falsifying/counter claim whose evidence must be in the task packet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: StrictStr = Field(min_length=1)
    direction: Literal["COUNTER"] = "COUNTER"
    statement: StrictStr = Field(min_length=1, max_length=4_000)
    evidence_ids: list[StrictStr] = Field(min_length=1, max_length=32)
    deterministic_metric_ids: list[StrictStr] = Field(default_factory=list, max_length=32)
    confidence: StrictFloat = Field(ge=0, le=1)

    @property
    def claim_id(self) -> str:
        return self.id

    @field_validator("evidence_ids", "deterministic_metric_ids")
    @classmethod
    def validate_unique_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)


class ResearchFinding(BaseModel):
    """One analyst's structured, untrusted research finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["research_finding_v1"] = "research_finding_v1"
    id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    role: AnalystRole
    question_id: StrictStr = Field(min_length=1)
    dimension: BusinessQualityDimensionName | None = None
    summary: StrictStr = Field(min_length=1, max_length=8_000)
    supporting_claims: list[EvidenceClaim] = Field(default_factory=list, max_length=64)
    counter_evidence_claims: list[CounterEvidenceClaim] = Field(default_factory=list, max_length=64)
    proposed_score: StrictInt | None = Field(default=None, ge=0, le=5)
    confidence: ConfidenceLevel
    deterministic_metric_ids: list[StrictStr] = Field(default_factory=list, max_length=64)
    unresolved_questions: list[StrictStr] = Field(default_factory=list, max_length=64)
    counter_evidence_checked: StrictBool = False
    proposed_adjustments: list[Adjustment] = Field(default_factory=list, max_length=32)

    @property
    def evidence_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                evidence_id
                for claim in (*self.supporting_claims, *self.counter_evidence_claims)
                for evidence_id in claim.evidence_ids
            )
        )

    @field_validator("deterministic_metric_ids", "unresolved_questions")
    @classmethod
    def validate_unique_lists(cls, value: list[str]) -> list[str]:
        return _unique(value)

    @model_validator(mode="after")
    def validate_claim_identity(self) -> Self:
        claim_ids = [claim.id for claim in (*self.supporting_claims, *self.counter_evidence_claims)]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("research finding claim IDs must be unique")
        adjustment_ids = [adjustment.id for adjustment in self.proposed_adjustments]
        if len(adjustment_ids) != len(set(adjustment_ids)):
            raise ValueError("research finding adjustment IDs must be unique")
        return self


class AgentRunMetadata(BaseModel):
    """Safe execution metadata; it intentionally has no raw provider payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_mode: AnalystExecutionMode = AnalystExecutionMode.EXTERNAL
    provider_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    model_id: StrictStr | None = Field(default=None, min_length=1, max_length=256)
    model_version: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    prompt_version: StrictStr = Field(default=RESEARCH_PROMPT_VERSION, min_length=1)
    protocol_version: StrictStr = Field(default=RESEARCH_PROTOCOL_VERSION, min_length=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)
    timeout_seconds: StrictFloat | None = Field(default=None, gt=0)
    max_context_items: StrictInt | None = Field(default=None, gt=0)
    notes: StrictStr | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_times(self) -> Self:
        if self.started_at is not None and self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at must not precede started_at")
        return self


class ResearchTask(BaseModel):
    """The exact input envelope passed to an injected analyst client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["research_task_v1"] = "research_task_v1"
    task_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    role: AnalystRole
    question: ResearchQuestion
    packet: EvidencePacket
    context_run_ids: list[StrictStr] = Field(default_factory=list, max_length=32)
    context_findings: list[ResearchFinding] = Field(default_factory=list, max_length=32)
    max_output_claims: StrictInt = Field(default=64, gt=0, le=128)
    max_unresolved_questions: StrictInt = Field(default=64, gt=0, le=128)
    prompt_version: StrictStr = Field(default=RESEARCH_PROMPT_VERSION, min_length=1)
    protocol_version: StrictStr = Field(default=RESEARCH_PROTOCOL_VERSION, min_length=1)
    task_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("context_run_ids")
    @classmethod
    def validate_unique_run_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)

    @model_validator(mode="after")
    def validate_task_scope(self) -> Self:
        if (
            self.packet.analysis_id != self.analysis_id
            or self.packet.listing_id != self.listing_id
            or self.packet.as_of != self.as_of
            or self.packet.profile_id != self.profile_id
            or self.packet.role is not self.role
            or self.packet.question.id != self.question.id
        ):
            raise ValueError("research task and evidence packet scope must match")
        if len(self.context_run_ids) != len(self.context_findings):
            raise ValueError("context_run_ids and context_findings must have equal length")
        for finding in self.context_findings:
            if (
                finding.analysis_id != self.analysis_id
                or finding.listing_id != self.listing_id
                or finding.as_of != self.as_of
            ):
                raise ValueError("context finding scope does not match research task")
            if not set(finding.evidence_ids).issubset(self.packet.available_evidence_ids):
                raise ValueError("context finding cites evidence outside the task packet")
            if not set(finding.deterministic_metric_ids).issubset(self.packet.metric_ids):
                raise ValueError("context finding cites a metric outside the task packet")
        expected = _hash_payload(self, "task_sha256")
        if self.task_sha256 != expected:
            raise ValueError("research task task_sha256 does not match task content")
        return self

    @classmethod
    def build(
        cls,
        *,
        analysis_id: str,
        listing_id: str,
        as_of: date,
        profile_id: str,
        role: AnalystRole,
        question: ResearchQuestion,
        packet: EvidencePacket,
        context_run_ids: list[str] | None = None,
        context_findings: list[ResearchFinding] | None = None,
        max_output_claims: int = 64,
        max_unresolved_questions: int = 64,
        prompt_version: str = RESEARCH_PROMPT_VERSION,
        protocol_version: str = RESEARCH_PROTOCOL_VERSION,
    ) -> ResearchTask:
        payload = {
            "contract": "research_task_v1",
            "task_id": "pending",
            "analysis_id": analysis_id,
            "listing_id": listing_id,
            "as_of": as_of.isoformat(),
            "profile_id": profile_id,
            "role": role.value,
            "question": question.model_dump(mode="json"),
            "packet": packet.model_dump(mode="json"),
            "context_run_ids": context_run_ids or [],
            "context_findings": [
                finding.model_dump(mode="json") for finding in (context_findings or [])
            ],
            "max_output_claims": max_output_claims,
            "max_unresolved_questions": max_unresolved_questions,
            "prompt_version": prompt_version,
            "protocol_version": protocol_version,
        }
        task_id = deterministic_id(
            "research-task",
            analysis_id,
            listing_id,
            as_of.isoformat(),
            profile_id,
            role.value,
            question.id,
            packet.packet_id,
            context_run_ids or [],
        )
        payload["task_id"] = task_id
        task_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        payload["task_sha256"] = task_sha256
        return cls.model_validate(payload)


class AnalystRun(BaseModel):
    """Persisted output of one model-neutral analyst invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["analyst_run_v1"] = "analyst_run_v1"
    run_id: StrictStr = Field(min_length=1)
    task_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    role: AnalystRole
    question_id: StrictStr = Field(min_length=1)
    dimension: BusinessQualityDimensionName | None = None
    packet_id: StrictStr = Field(min_length=1)
    available_evidence_ids: list[StrictStr] = Field(default_factory=list, max_length=128)
    finding: ResearchFinding
    metadata: AgentRunMetadata
    status: AnalystRunStatus = AnalystRunStatus.COMPLETED
    protocol_version: StrictStr = Field(default=RESEARCH_PROTOCOL_VERSION, min_length=1)
    input_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    output_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("available_evidence_ids")
    @classmethod
    def validate_unique_evidence_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)

    @model_validator(mode="after")
    def validate_run_content_hash(self) -> Self:
        finding = self.finding
        if (
            finding.analysis_id != self.analysis_id
            or finding.listing_id != self.listing_id
            or finding.as_of != self.as_of
            or finding.role is not self.role
            or finding.question_id != self.question_id
            or finding.dimension != self.dimension
        ):
            raise ValueError("analyst run and finding scope must match")
        if not set(finding.evidence_ids).issubset(self.available_evidence_ids):
            raise ValueError("analyst finding cites evidence outside its packet")
        for adjustment in finding.proposed_adjustments:
            if adjustment.status.value != "PROPOSED":
                raise ValueError("analyst-originated adjustments must remain PROPOSED")
            if adjustment.proposed_by.value != "LLM" or adjustment.approved_by is not None:
                raise ValueError("analyst-originated adjustments cannot be approved")
        expected_output = _hash_payload(self, "run_id", "input_sha256", "output_sha256")
        if self.output_sha256 != expected_output:
            raise ValueError("analyst run output_sha256 does not match run content")
        return self

    def validate_against_task(self, task: ResearchTask) -> None:
        """Validate the untrusted response against the exact supplied task."""

        if (
            self.task_id != task.task_id
            or self.analysis_id != task.analysis_id
            or self.listing_id != task.listing_id
            or self.as_of != task.as_of
            or self.profile_id != task.profile_id
            or self.role is not task.role
            or self.question_id != task.question.id
            or self.packet_id != task.packet.packet_id
            or self.available_evidence_ids != task.packet.available_evidence_ids
        ):
            raise ValueError("analyst run does not match its research task")
        if self.input_sha256 != task.task_sha256:
            raise ValueError("analyst run input hash does not match its research task")
        if not set(self.finding.evidence_ids).issubset(task.packet.available_evidence_ids):
            raise ValueError("analyst run cites evidence not supplied in its task")
        if not set(self.finding.deterministic_metric_ids).issubset(task.packet.metric_ids):
            raise ValueError("analyst run cites a metric not supplied in its task")
        for adjustment in self.finding.proposed_adjustments:
            if adjustment.status.value != "PROPOSED":
                raise ValueError("analyst-originated adjustments must remain PROPOSED")
            if adjustment.proposed_by.value != "LLM" or adjustment.approved_by is not None:
                raise ValueError("analyst-originated adjustments cannot be approved")
            if not set(adjustment.source_evidence_ids).issubset(task.packet.available_evidence_ids):
                raise ValueError("adjustment cites evidence not supplied in its task")

    @classmethod
    def build(
        cls,
        task: ResearchTask,
        finding: ResearchFinding,
        metadata: AgentRunMetadata | None = None,
        *,
        execution_mode: AnalystExecutionMode = AnalystExecutionMode.EXTERNAL,
    ) -> AnalystRun:
        """Build a run with deterministic IDs after validating its proposal."""

        active_metadata = metadata or AgentRunMetadata(execution_mode=execution_mode)
        if active_metadata.protocol_version != task.protocol_version:
            active_metadata = active_metadata.model_copy(
                update={"protocol_version": task.protocol_version}
            )
        if active_metadata.prompt_version != task.prompt_version:
            active_metadata = active_metadata.model_copy(
                update={"prompt_version": task.prompt_version}
            )
        payload = {
            "contract": "analyst_run_v1",
            "task_id": task.task_id,
            "analysis_id": task.analysis_id,
            "listing_id": task.listing_id,
            "as_of": task.as_of.isoformat(),
            "profile_id": task.profile_id,
            "role": task.role.value,
            "question_id": task.question.id,
            "dimension": task.question.dimension,
            "packet_id": task.packet.packet_id,
            "available_evidence_ids": list(task.packet.available_evidence_ids),
            "finding": finding.model_dump(mode="json"),
            "metadata": active_metadata.model_dump(mode="json"),
            "status": AnalystRunStatus.COMPLETED.value,
            "protocol_version": task.protocol_version,
        }
        output_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        run_id = deterministic_id("analyst-run", task.task_sha256, output_sha256)
        payload.update(
            {
                "run_id": run_id,
                "input_sha256": task.task_sha256,
                "output_sha256": output_sha256,
            }
        )
        run = cls.model_validate(payload)
        run.validate_against_task(task)
        return run


class DimensionResearchResult(BaseModel):
    """One complete Quality Analyst/Skeptic/Adjudicator vertical slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["dimension_research_result_v1"] = "dimension_research_result_v1"
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    dimension: BusinessQualityDimensionName
    packets: list[EvidencePacket] = Field(min_length=3, max_length=3)
    tasks: list[ResearchTask] = Field(min_length=3, max_length=3)
    analyst_runs: list[AnalystRun] = Field(min_length=3, max_length=3)
    proposed_dimension: BusinessQualityDimension
    proposed_adjustments: list[Adjustment] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_vertical_slice(self) -> Self:
        if any(
            item.analysis_id != self.analysis_id
            or item.listing_id != self.listing_id
            or item.as_of != self.as_of
            or item.profile_id != self.profile_id
            for item in (*self.packets, *self.tasks, *self.analyst_runs)
        ):
            raise ValueError("dimension research artifacts have inconsistent scope")
        expected_roles = (
            AnalystRole.QUALITY_ANALYST,
            AnalystRole.SKEPTIC,
            AnalystRole.ADJUDICATOR,
        )
        if tuple(item.role for item in self.packets) != expected_roles:
            raise ValueError("dimension packets must be ordered Quality/Skeptic/Adjudicator")
        if tuple(item.role for item in self.tasks) != expected_roles:
            raise ValueError("dimension tasks must be ordered Quality/Skeptic/Adjudicator")
        if tuple(item.role for item in self.analyst_runs) != expected_roles:
            raise ValueError("dimension runs must be ordered Quality/Skeptic/Adjudicator")
        if any(item.question.dimension != self.dimension for item in self.packets):
            raise ValueError("dimension packet question does not match the vertical slice")
        if any(item.question.dimension != self.dimension for item in self.tasks):
            raise ValueError("dimension task question does not match the vertical slice")
        if any(item.dimension != self.dimension for item in self.analyst_runs):
            raise ValueError("dimension run does not match the vertical slice")
        for index, (packet, task, run) in enumerate(
            zip(self.packets, self.tasks, self.analyst_runs, strict=True)
        ):
            if task.packet.packet_id != packet.packet_id:
                raise ValueError(f"dimension task {index} does not reference its packet")
            if run.task_id != task.task_id or run.packet_id != packet.packet_id:
                raise ValueError(f"dimension run {index} does not reference its task/packet")
        adjudicator_evidence_ids = set(self.packets[-1].available_evidence_ids)
        if not set(self.proposed_dimension.supporting_evidence_ids).issubset(
            adjudicator_evidence_ids
        ) or not set(self.proposed_dimension.counter_evidence_ids).issubset(
            adjudicator_evidence_ids
        ):
            raise ValueError("proposed dimension cites evidence outside its adjudicator packet")
        run_proposals: list[Adjustment] = []
        seen_proposal_ids: set[str] = set()
        for run in self.analyst_runs:
            for adjustment in run.finding.proposed_adjustments:
                if adjustment.id not in seen_proposal_ids:
                    seen_proposal_ids.add(adjustment.id)
                    run_proposals.append(adjustment)
        if [item.model_dump(mode="json") for item in self.proposed_adjustments] != [
            item.model_dump(mode="json")
            for item in sorted(run_proposals, key=lambda value: value.id)
        ]:
            raise ValueError("dimension proposals do not match analyst run proposals")
        if self.proposed_dimension.dimension != self.dimension:
            raise ValueError("proposed dimension does not match the vertical slice")
        return self


class ResearchSession(BaseModel):
    """Resume-friendly index of persisted packets, tasks, runs and outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["research_session_v1"] = "research_session_v1"
    session_id: StrictStr = Field(min_length=1)
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    protocol_version: StrictStr = Field(default=RESEARCH_PROTOCOL_VERSION, min_length=1)
    packet_ids: list[StrictStr] = Field(default_factory=list, max_length=1_024)
    task_ids: list[StrictStr] = Field(default_factory=list, max_length=1_024)
    analyst_run_ids: list[StrictStr] = Field(default_factory=list, max_length=1_024)
    proposed_adjustment_ids: list[StrictStr] = Field(default_factory=list, max_length=256)
    accepted_adjustment_ids: list[StrictStr] = Field(default_factory=list, max_length=256)
    business_quality_available: StrictBool = False
    business_quality_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    final_analysis_id: StrictStr | None = Field(default=None, min_length=1)
    final_analysis_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    final_trace_artifact_id: StrictStr | None = Field(default=None, min_length=1)
    report_id: StrictStr | None = Field(default=None, min_length=1)

    @field_validator(
        "packet_ids",
        "task_ids",
        "analyst_run_ids",
        "proposed_adjustment_ids",
        "accepted_adjustment_ids",
    )
    @classmethod
    def validate_unique_artifact_ids(cls, value: list[str]) -> list[str]:
        return _unique(value)

    @classmethod
    def build(
        cls,
        *,
        analysis_id: str,
        listing_id: str,
        as_of: date,
        profile_id: str,
        packet_ids: list[str],
        task_ids: list[str],
        analyst_run_ids: list[str],
        proposed_adjustment_ids: list[str],
        accepted_adjustment_ids: list[str],
        business_quality_available: bool,
        business_quality_artifact_id: str | None = None,
        final_analysis_id: str | None = None,
        final_analysis_artifact_id: str | None = None,
        final_trace_artifact_id: str | None = None,
        report_id: str | None = None,
        protocol_version: str = RESEARCH_PROTOCOL_VERSION,
    ) -> ResearchSession:
        session_id = deterministic_id(
            "research-session",
            analysis_id,
            listing_id,
            as_of.isoformat(),
            profile_id,
            packet_ids,
            task_ids,
            analyst_run_ids,
            proposed_adjustment_ids,
            accepted_adjustment_ids,
            final_analysis_id,
            final_analysis_artifact_id,
            final_trace_artifact_id,
        )
        quality_artifact_id = business_quality_artifact_id
        if quality_artifact_id is None and business_quality_available:
            quality_artifact_id = session_id
        return cls(
            session_id=session_id,
            analysis_id=analysis_id,
            listing_id=listing_id,
            as_of=as_of,
            profile_id=profile_id,
            protocol_version=protocol_version,
            packet_ids=packet_ids,
            task_ids=task_ids,
            analyst_run_ids=analyst_run_ids,
            proposed_adjustment_ids=proposed_adjustment_ids,
            accepted_adjustment_ids=accepted_adjustment_ids,
            business_quality_available=business_quality_available,
            business_quality_artifact_id=quality_artifact_id,
            final_analysis_id=final_analysis_id,
            final_analysis_artifact_id=final_analysis_artifact_id,
            final_trace_artifact_id=final_trace_artifact_id,
            report_id=report_id,
        )


class BusinessQualityResearchResult(BaseModel):
    """Validated eight-dimension result plus the runs that produced it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["business_quality_research_v1"] = "business_quality_research_v1"
    analysis_id: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    dimension_results: list[BusinessQualityDimension] = Field(min_length=8, max_length=8)
    dimension_runs: list[DimensionResearchResult] = Field(min_length=8, max_length=8)
    business_quality: BusinessQuality
    packets: list[EvidencePacket] = Field(min_length=1, max_length=64)
    tasks: list[ResearchTask] = Field(min_length=1, max_length=64)
    analyst_runs: list[AnalystRun] = Field(min_length=1, max_length=64)
    proposed_adjustments: list[Adjustment] = Field(default_factory=list, max_length=256)
    session_id: StrictStr | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_scope_and_completeness(self) -> Self:
        if (
            any(item.analysis_id != self.analysis_id for item in self.packets)
            or any(item.listing_id != self.listing_id for item in self.packets)
            or any(item.as_of != self.as_of for item in self.packets)
            or any(item.profile_id != self.profile_id for item in self.packets)
            or any(
                item.analysis_id != self.analysis_id
                or item.listing_id != self.listing_id
                or item.as_of != self.as_of
                or item.profile_id != self.profile_id
                for item in self.tasks
            )
            or any(
                item.analysis_id != self.analysis_id
                or item.listing_id != self.listing_id
                or item.as_of != self.as_of
                or item.profile_id != self.profile_id
                for item in self.analyst_runs
            )
            or any(
                item.analysis_id != self.analysis_id
                or item.listing_id != self.listing_id
                or item.as_of != self.as_of
                or item.profile_id != self.profile_id
                for item in self.dimension_runs
            )
        ):
            raise ValueError("business-quality research artifacts have inconsistent scope")
        if len(self.dimension_results) != 8:
            raise ValueError("business-quality research must contain all eight dimensions")
        if len(self.dimension_runs) != 8:
            raise ValueError("business-quality research must contain eight vertical slices")
        dimension_names = [item.dimension for item in self.dimension_runs]
        result_names = [item.dimension for item in self.dimension_results]
        if dimension_names != list(_BUSINESS_QUALITY_DIMENSION_ORDER):
            raise ValueError("business-quality vertical slices must cover B01 through B08")
        if result_names != list(_BUSINESS_QUALITY_DIMENSION_ORDER):
            raise ValueError("dimension results and vertical slices are out of order")
        if self.dimension_results != self.business_quality.dimension_results:
            raise ValueError("dimension_results must contain deterministic validated scores")
        flattened_runs = [run for item in self.dimension_runs for run in item.analyst_runs]
        if [run.run_id for run in flattened_runs] != [run.run_id for run in self.analyst_runs]:
            raise ValueError("business-quality runs do not match vertical slices")
        flattened_packets = [packet for item in self.dimension_runs for packet in item.packets]
        flattened_tasks = [task for item in self.dimension_runs for task in item.tasks]
        if [packet.packet_id for packet in flattened_packets] != [
            packet.packet_id for packet in self.packets
        ]:
            raise ValueError("business-quality packets do not match vertical slices")
        if [task.task_id for task in flattened_tasks] != [task.task_id for task in self.tasks]:
            raise ValueError("business-quality tasks do not match vertical slices")
        run_proposals: dict[str, Adjustment] = {}
        for run in self.analyst_runs:
            for adjustment in run.finding.proposed_adjustments:
                previous = run_proposals.get(adjustment.id)
                if previous is not None and previous != adjustment:
                    raise ValueError(f"conflicting business-quality proposal: {adjustment.id}")
                run_proposals[adjustment.id] = adjustment
        if [item.id for item in self.proposed_adjustments] != sorted(run_proposals):
            raise ValueError("business-quality proposals do not match analyst runs")
        return self


def packet_fact_from_fact(fact: Fact) -> PacketFact:
    """Public conversion helper used by packet builders and external runtimes."""

    return PacketFact.from_fact(fact)


__all__ = [
    "AnalystExecutionMode",
    "AnalystRole",
    "AnalystRun",
    "AnalystRunStatus",
    "AgentRunMetadata",
    "BusinessQualityDimensionName",
    "BusinessQualityResearchResult",
    "CounterEvidenceClaim",
    "DeterministicMetric",
    "DimensionResearchResult",
    "EvidenceClaim",
    "EvidencePacket",
    "PacketFact",
    "ResearchFinding",
    "ResearchIntent",
    "ResearchQuestion",
    "ResearchSession",
    "ResearchTask",
    "RESEARCH_CONTRACT_VERSION",
    "RESEARCH_PROTOCOL_VERSION",
    "RESEARCH_PROMPT_VERSION",
    "packet_fact_from_fact",
]
