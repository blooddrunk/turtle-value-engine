"""Typed, versioned contracts for Phase 6-C re-analysis execution.

The execution contracts deliberately live outside ``monitoring``.  The latter
is the pure Phase 6-A planner; this package owns the separate lifecycle of
preparation, research, deterministic analysis and surface artifacts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from turtle_value_engine.monitoring.canonical import (
    canonical_datetime_str,
    canonical_json_bytes,
    canonical_sha256,
    normalize_utc,
)
from turtle_value_engine.monitoring.models import CanonicalEventType
from turtle_value_engine.monitoring.policy import ImpactClass

REANALYSIS_EXECUTION_POLICY_ID: Literal["reanalysis-execution-v1"] = (
    "reanalysis-execution-v1"
)
REANALYSIS_EXECUTION_POLICY_VERSION: Literal["1.0.0"] = "1.0.0"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_ZERO_HASH = "0" * 64
_SKIP_HASH_CONTEXT_KEY = "skip_derived_hash_validation"


class ReanalysisJobStatus(StrEnum):
    """Terminal states persisted by the synchronous Phase 6-C executor."""

    NO_ACTION = "NO_ACTION"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"


class ReanalysisFailureCode(StrEnum):
    """Stable non-secret blocker/failure categories."""

    BLOCKED_RESEARCH_RUNTIME = "BLOCKED_RESEARCH_RUNTIME"
    PREPARATION_FAILED = "PREPARATION_FAILED"
    RESEARCH_FAILED = "RESEARCH_FAILED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    SURFACE_FAILED = "SURFACE_FAILED"
    INVALID_PRIOR_ANALYSIS = "INVALID_PRIOR_ANALYSIS"
    JOB_STORE_WRITE_FAILED = "JOB_STORE_WRITE_FAILED"


class ReanalysisCapabilitySummaryV1(BaseModel):
    """Non-secret capability facts captured with every execution result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    network_allowed: StrictBool
    preparation_mode: Literal["CACHE_ONLY", "LIVE"]
    model_allowed: StrictBool
    research_runtime_available: StrictBool
    accepted_adjustments_supplied: StrictBool


class _ExecutionContract(BaseModel):
    """Canonical JSON/hash plumbing shared by persisted execution artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def canonical_payload(self, *, exclude: set[str] | None = None) -> dict:
        return self.model_dump(
            mode="json", exclude=exclude, warnings=False
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())

    @classmethod
    def _coerced(cls, values: dict) -> Self:
        payload = dict(values)
        for name, field in cls.model_fields.items():
            if name in {"job_id", "attempt_id", "content_sha256"} and field.is_required():
                payload.setdefault(name, _ZERO_HASH)
        return cls.model_validate(payload, context={_SKIP_HASH_CONTEXT_KEY: True})


def _hash_checks_enabled(info: ValidationInfo) -> bool:
    context = info.context
    return not (isinstance(context, dict) and context.get(_SKIP_HASH_CONTEXT_KEY))


def _normalize_datetime(value: datetime) -> datetime:
    return normalize_utc(value)


def reanalysis_job_id(
    source_run_id: str,
    request_id: str,
    execution_as_of: datetime,
    *,
    policy_id: str = REANALYSIS_EXECUTION_POLICY_ID,
    policy_version: str = REANALYSIS_EXECUTION_POLICY_VERSION,
) -> str:
    """Derive the stable identity of one committed monitoring request."""

    return canonical_sha256(
        {
            "domain": "tve-reanalysis-job-v1",
            "source_run_id": source_run_id,
            "request_id": request_id,
            "execution_policy_id": policy_id,
            "execution_policy_version": policy_version,
            "execution_as_of": canonical_datetime_str(execution_as_of),
        }
    )


class ReanalysisJobV1(_ExecutionContract):
    """One durable result for one deterministic source request identity."""

    contract: Literal["reanalysis_job_v1"] = "reanalysis_job_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    job_id: StrictStr = Field(pattern=_HASH_PATTERN)
    source_run_id: StrictStr = Field(pattern=_HASH_PATTERN)
    request_id: StrictStr = Field(pattern=_HASH_PATTERN)
    watchlist_id: StrictStr = Field(min_length=1, max_length=100)
    listing_id: StrictStr = Field(min_length=1, max_length=32)
    profile_id: StrictStr = Field(min_length=1, max_length=100)
    impact: ImpactClass
    event_ids: list[StrictStr] = Field(min_length=1, max_length=256)
    event_types: list[CanonicalEventType] = Field(min_length=1, max_length=256)
    source_watchlist_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    event_batch_id: StrictStr = Field(pattern=_HASH_PATTERN)
    committed_run_proof_id: StrictStr = Field(pattern=_HASH_PATTERN)
    execution_as_of: datetime
    execution_policy_id: Literal["reanalysis-execution-v1"] = (
        REANALYSIS_EXECUTION_POLICY_ID
    )
    execution_policy_version: Literal["1.0.0"] = REANALYSIS_EXECUTION_POLICY_VERSION
    capabilities: ReanalysisCapabilitySummaryV1
    status: ReanalysisJobStatus
    failure_code: ReanalysisFailureCode | None = None
    message: StrictStr | None = Field(default=None, max_length=512)
    evidence_codes: list[StrictStr] = Field(default_factory=list, max_length=32)
    prior_analysis_id: StrictStr | None = Field(default=None, min_length=1)
    prior_analysis_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    normalized_input_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    analysis_id: StrictStr | None = Field(default=None, min_length=1)
    analysis_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    trace_id: StrictStr | None = Field(default=None, min_length=1)
    trace_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    research_session_id: StrictStr | None = Field(default=None, min_length=1)
    research_session_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    report_id: StrictStr | None = Field(default=None, min_length=1)
    report_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    surface_id: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    surface_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    _normalize_execution_as_of = field_validator("execution_as_of")(_normalize_datetime)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "domain": "tve-reanalysis-job-v1",
            "source_run_id": self.source_run_id,
            "request_id": self.request_id,
            "execution_policy_id": self.execution_policy_id,
            "execution_policy_version": self.execution_policy_version,
            "execution_as_of": canonical_datetime_str(self.execution_as_of),
        }

    @model_validator(mode="after")
    def _validate_job(self, info: ValidationInfo) -> Self:
        if len(self.event_ids) != len(set(self.event_ids)):
            raise ValueError("reanalysis job event_ids must be unique")
        if len(self.event_ids) != len(self.event_types):
            raise ValueError("reanalysis job event_ids and event_types must align")
        if len(self.evidence_codes) != len(set(self.evidence_codes)):
            raise ValueError("reanalysis job evidence_codes must be unique")
        if self.prior_analysis_id is None and self.prior_analysis_sha256 is not None:
            raise ValueError("prior_analysis_sha256 requires prior_analysis_id")
        if self.prior_analysis_id is not None and self.prior_analysis_sha256 is None:
            raise ValueError("prior_analysis_id requires prior_analysis_sha256")

        output_fields = (
            self.normalized_input_sha256,
            self.analysis_id,
            self.analysis_sha256,
            self.trace_id,
            self.trace_sha256,
            self.research_session_id,
            self.research_session_sha256,
            self.report_id,
            self.report_sha256,
            self.surface_id,
            self.surface_sha256,
        )
        if (
            self.status is ReanalysisJobStatus.NO_ACTION
            and self.impact is not ImpactClass.NO_REANALYSIS
        ):
            raise ValueError("NO_ACTION is only valid for NO_REANALYSIS")
        if (
            self.status is ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED
            and self.impact is not ImpactClass.URGENT_MANUAL_REVIEW
        ):
            raise ValueError("MANUAL_REVIEW_REQUIRED is only valid for URGENT_MANUAL_REVIEW")
        if (
            self.status is ReanalysisJobStatus.BLOCKED
            and self.impact is not ImpactClass.FULL_REANALYSIS
        ):
            raise ValueError("BLOCKED is only valid for FULL_REANALYSIS")
        if self.status is ReanalysisJobStatus.SUCCEEDED and self.impact not in {
            ImpactClass.PARTIAL_REANALYSIS,
            ImpactClass.FULL_REANALYSIS,
        }:
            raise ValueError("SUCCEEDED is only valid for PARTIAL_REANALYSIS or FULL_REANALYSIS")
        if self.status is ReanalysisJobStatus.SUCCEEDED:
            if any(value is None for value in output_fields[:5]) or any(
                value is None for value in output_fields[-2:]
            ):
                raise ValueError(
                    "successful reanalysis job is missing analysis/trace/surface outputs"
                )
            if self.impact is ImpactClass.FULL_REANALYSIS and (
                self.research_session_id is None
                or self.research_session_sha256 is None
                or self.report_id is None
                or self.report_sha256 is None
            ):
                raise ValueError("successful full reanalysis job is missing research outputs")
            if self.impact is ImpactClass.PARTIAL_REANALYSIS and any(
                value is not None
                for value in output_fields[5:9]
            ):
                raise ValueError(
                    "successful partial reanalysis job cannot contain research outputs"
                )
            if self.failure_code is not None:
                raise ValueError("successful reanalysis job cannot contain failure_code")
        elif self.status in {
            ReanalysisJobStatus.NO_ACTION,
            ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
        }:
            if any(value is not None for value in output_fields):
                raise ValueError("non-executing reanalysis job cannot contain output artifacts")
            if self.failure_code is not None:
                raise ValueError("non-executing reanalysis job cannot contain failure_code")
            if self.message is None:
                raise ValueError("non-executing reanalysis job requires a bounded message")
        else:
            if self.failure_code is None:
                raise ValueError("blocked/failed reanalysis job requires failure_code")
            if any(value is not None for value in output_fields):
                raise ValueError("blocked/failed reanalysis job cannot contain output artifacts")
            if self.message is None:
                raise ValueError("blocked/failed reanalysis job requires a bounded message")

        if _hash_checks_enabled(info):
            expected_job_id = reanalysis_job_id(
                self.source_run_id,
                self.request_id,
                self.execution_as_of,
                policy_id=self.execution_policy_id,
                policy_version=self.execution_policy_version,
            )
            if self.job_id != expected_job_id:
                raise ValueError("reanalysis job_id does not match deterministic identity")
            expected_content = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected_content:
                raise ValueError("reanalysis job content_sha256 does not match canonical content")
        return self

    @classmethod
    def build(cls, **values: object) -> ReanalysisJobV1:
        coerced = cls._coerced(dict(values))
        job_id = reanalysis_job_id(
            coerced.source_run_id,
            coerced.request_id,
            coerced.execution_as_of,
            policy_id=coerced.execution_policy_id,
            policy_version=coerced.execution_policy_version,
        )
        payload = coerced.canonical_payload(exclude={"job_id", "content_sha256"})
        payload["job_id"] = job_id
        content = canonical_sha256(payload)
        return cls.model_validate(payload | {"content_sha256": content})


class ReanalysisJobAttemptV1(_ExecutionContract):
    """Immutable terminal attempt; non-terminal state is deliberately not persisted."""

    contract: Literal["reanalysis_job_attempt_v1"] = "reanalysis_job_attempt_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    job: ReanalysisJobV1
    attempt_number: StrictInt = Field(ge=1)
    attempt_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "domain": "tve-reanalysis-job-attempt-v1",
            "job_id": self.job.job_id,
            "attempt_number": self.attempt_number,
        }

    @model_validator(mode="after")
    def _validate_attempt(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            expected_id = canonical_sha256(self._identity_payload())
            if self.attempt_id != expected_id:
                raise ValueError("reanalysis attempt_id does not match deterministic identity")
            expected_content = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected_content:
                raise ValueError("reanalysis attempt content_sha256 does not match content")
        return self

    @classmethod
    def build(cls, *, job: ReanalysisJobV1, attempt_number: int) -> ReanalysisJobAttemptV1:
        payload = {
            "job": job,
            "attempt_number": attempt_number,
            "attempt_id": _ZERO_HASH,
            "content_sha256": _ZERO_HASH,
        }
        coerced = cls.model_validate(payload, context={_SKIP_HASH_CONTEXT_KEY: True})
        attempt_id = canonical_sha256(coerced._identity_payload())
        content_payload = coerced.canonical_payload(exclude={"attempt_id", "content_sha256"})
        content = canonical_sha256(content_payload | {"attempt_id": attempt_id})
        return cls.model_validate(
            content_payload | {"attempt_id": attempt_id, "content_sha256": content}
        )


class ReanalysisJobPointerV1(_ExecutionContract):
    """Atomic pointer to the latest immutable attempt for one job identity."""

    contract: Literal["reanalysis_job_pointer_v1"] = "reanalysis_job_pointer_v1"
    schema_version: Literal["1.0.0"] = "1.0.0"
    job_id: StrictStr = Field(pattern=_HASH_PATTERN)
    attempt_id: StrictStr = Field(pattern=_HASH_PATTERN)
    attempt_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def _validate_pointer(self, info: ValidationInfo) -> Self:
        if _hash_checks_enabled(info):
            expected = canonical_sha256(self.canonical_payload(exclude={"content_sha256"}))
            if self.content_sha256 != expected:
                raise ValueError("reanalysis job pointer content_sha256 mismatch")
        return self

    @classmethod
    def build(cls, **values: object) -> ReanalysisJobPointerV1:
        payload = dict(values)
        payload["content_sha256"] = _ZERO_HASH
        coerced = cls.model_validate(payload, context={_SKIP_HASH_CONTEXT_KEY: True})
        identity_payload = coerced.canonical_payload(exclude={"content_sha256"})
        return cls.model_validate(
            identity_payload | {"content_sha256": canonical_sha256(identity_payload)}
        )


__all__ = [
    "REANALYSIS_EXECUTION_POLICY_ID",
    "REANALYSIS_EXECUTION_POLICY_VERSION",
    "ReanalysisCapabilitySummaryV1",
    "ReanalysisFailureCode",
    "ReanalysisJobAttemptV1",
    "ReanalysisJobPointerV1",
    "ReanalysisJobStatus",
    "ReanalysisJobV1",
    "reanalysis_job_id",
]
