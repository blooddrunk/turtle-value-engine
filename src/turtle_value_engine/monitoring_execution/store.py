"""Separate immutable/atomic storage for Phase 6-C execution jobs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from turtle_value_engine.models import CompanyAnalysis, NormalizedCompanyInput
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.research.contracts import ResearchSession
from turtle_value_engine.research.report import ResearchReport
from turtle_value_engine.surface.contracts import ResearchSurfaceSnapshotV1
from turtle_value_engine.traceability import DecisionTrace

from .contracts import (
    ReanalysisJobAttemptV1,
    ReanalysisJobPointerV1,
    ReanalysisJobStatus,
    ReanalysisJobV1,
)

ArtifactKind = Literal[
    "normalized-input",
    "analysis",
    "trace",
    "research-session",
    "report",
    "surface",
]
WriteKind = Literal["artifact", "job", "pointer"]
FailureInjector = Callable[[Path, WriteKind], None]
ModelT = TypeVar("ModelT", bound=BaseModel)


class ReanalysisJobStoreError(ValueError):
    """Raised when an execution artifact is missing, corrupt or conflicting."""


@dataclass(frozen=True, slots=True)
class ReanalysisArtifactBundle:
    """Explicit output artifacts bound to one successful job."""

    normalized_input: NormalizedCompanyInput
    analysis: CompanyAnalysis
    trace: DecisionTrace
    surface: ResearchSurfaceSnapshotV1
    research_session: ResearchSession | None = None
    report: ResearchReport | None = None


def _model_bytes(model: BaseModel) -> bytes:
    return canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n"


def _model_sha256(model: BaseModel) -> str:
    return hashlib.sha256(
        canonical_json_bytes(model.model_dump(mode="json", warnings=False))
    ).hexdigest()


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


class ReanalysisJobStore:
    """Immutable result artifacts plus an atomically replaced latest pointer.

    PENDING/RUNNING are intentionally not persisted.  A process crash before
    the terminal attempt is written therefore leaves no false in-progress
    claim; a retry deterministically resumes by creating the next attempt.
    If the pointer write alone fails, the immutable attempt remains discoverable
    and a later retry reuses it without repeating provider/model work.
    """

    def __init__(self, root: str | Path, *, failure_injector=None) -> None:
        self.root = Path(root)
        self._failure_injector = failure_injector

    def attempt_path(self, attempt_id: str) -> Path:
        return self.root / "jobs" / "attempts" / f"{attempt_id}.json"

    def latest_path(self, job_id: str) -> Path:
        return self.root / "jobs" / "latest" / f"{job_id}.json"

    def artifact_path(self, kind: ArtifactKind, artifact_id: str) -> Path:
        if not artifact_id or "/" in artifact_id or "\\" in artifact_id:
            raise ValueError("artifact_id must be a non-empty path-safe identifier")
        return self.root / "artifacts" / kind / f"{artifact_id}.json"

    def _inject_failure(self, path: Path, kind: WriteKind) -> None:
        if self._failure_injector is not None:
            self._failure_injector(path, kind)

    def _write_immutable(self, path: Path, content: bytes) -> None:
        if path.is_symlink() or path.exists():
            if path.is_symlink() or not path.is_file():
                raise ReanalysisJobStoreError(f"execution artifact is not a regular file: {path}")
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise ReanalysisJobStoreError(
                    f"cannot read existing execution artifact: {exc}"
                ) from exc
            if existing != content:
                raise ReanalysisJobStoreError(
                    f"execution artifact {path.name} already has conflicting content"
                )
            return

        temporary_path: Path | None = None
        descriptor = -1
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_path, path)
            _fsync_directory(path.parent)
            temporary_path.unlink()
            temporary_path = None
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise ReanalysisJobStoreError(
                    f"cannot read existing execution artifact: {exc}"
                ) from exc
            if existing != content:
                raise ReanalysisJobStoreError(
                    f"execution artifact {path.name} already has conflicting content"
                )
        except OSError as exc:
            raise ReanalysisJobStoreError(
                f"cannot persist execution artifact {path}: {exc}"
            ) from exc
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

    def _write_pointer(self, path: Path, content: bytes) -> None:
        temporary_path: Path | None = None
        descriptor = -1
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            _fsync_directory(path.parent)
        except OSError as exc:
            raise ReanalysisJobStoreError(
                f"cannot update execution latest pointer {path}: {exc}"
            ) from exc
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

    def _commit_bytes(self, path: Path, content: bytes, kind: WriteKind) -> None:
        try:
            self._inject_failure(path, kind)
        except Exception as exc:
            raise ReanalysisJobStoreError(
                f"execution store write failed at {path}: {type(exc).__name__}"
            ) from exc
        if kind == "pointer":
            self._write_pointer(path, content)
        else:
            self._write_immutable(path, content)

    @staticmethod
    def _verify_regular_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise ReanalysisJobStoreError(f"execution artifact is missing or not a file: {path}")

    def _read_model(self, path: Path, model_type: type[ModelT]) -> ModelT:
        self._verify_regular_file(path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_number)
            model = model_type.model_validate(payload)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise ReanalysisJobStoreError(f"corrupt execution artifact {path}: {exc}") from exc
        if _model_bytes(model) != raw:
            raise ReanalysisJobStoreError(f"execution artifact {path.name} is not canonical")
        return model

    def _attempts(self, job_id: str) -> list[ReanalysisJobAttemptV1]:
        directory = self.root / "jobs" / "attempts"
        if not directory.exists():
            return []
        attempts: list[ReanalysisJobAttemptV1] = []
        for path in sorted(directory.glob("*.json")):
            attempt = self._read_model(path, ReanalysisJobAttemptV1)
            if attempt.job.job_id == job_id:
                attempts.append(attempt)
        return attempts

    def load_latest(self, job_id: str) -> ReanalysisJobAttemptV1 | None:
        """Read the atomic pointer, or recover an orphaned immutable attempt."""

        pointer_path = self.latest_path(job_id)
        if pointer_path.is_symlink() or pointer_path.exists():
            pointer = self._read_model(pointer_path, ReanalysisJobPointerV1)
            if pointer.job_id != job_id:
                raise ReanalysisJobStoreError("execution latest pointer belongs to another job")
            attempt = self._read_model(
                self.attempt_path(pointer.attempt_id), ReanalysisJobAttemptV1
            )
            if (
                attempt.job.job_id != job_id
                or attempt.attempt_id != pointer.attempt_id
                or attempt.content_sha256 != pointer.attempt_content_sha256
            ):
                raise ReanalysisJobStoreError("execution latest pointer does not match its attempt")
            return attempt

        attempts = self._attempts(job_id)
        if not attempts:
            return None
        highest = max(attempt.attempt_number for attempt in attempts)
        candidates = [attempt for attempt in attempts if attempt.attempt_number == highest]
        if len(candidates) != 1:
            raise ReanalysisJobStoreError("multiple conflicting latest execution attempts")
        return candidates[0]

    def _artifact_specs(
        self, job: ReanalysisJobV1, bundle: ReanalysisArtifactBundle | None
    ) -> list[tuple[ArtifactKind, str, BaseModel, str]]:
        if bundle is None:
            return []
        specs = [
            (
                "normalized-input",
                job.normalized_input_sha256 or "",
                bundle.normalized_input,
                job.normalized_input_sha256 or "",
            ),
            ("analysis", job.analysis_id or "", bundle.analysis, job.analysis_sha256 or ""),
            ("trace", job.trace_id or "", bundle.trace, job.trace_sha256 or ""),
            ("surface", job.surface_id or "", bundle.surface, job.surface_sha256 or ""),
        ]
        if bundle.research_session is not None:
            specs.append(
                (
                    "research-session",
                    job.research_session_id or "",
                    bundle.research_session,
                    job.research_session_sha256 or "",
                )
            )
        if bundle.report is not None:
            specs.append(
                ("report", job.report_id or "", bundle.report, job.report_sha256 or "")
            )
        return specs

    def save(
        self,
        job: ReanalysisJobV1,
        *,
        artifacts: ReanalysisArtifactBundle | None = None,
    ) -> ReanalysisJobAttemptV1:
        """Persist a terminal job and atomically publish its latest attempt."""

        existing = self.load_latest(job.job_id)
        if existing is not None:
            if existing.job.content_sha256 == job.content_sha256:
                if artifacts is not None:
                    self._persist_artifacts(job, artifacts)
                pointer = ReanalysisJobPointerV1.build(
                    job_id=existing.job.job_id,
                    attempt_id=existing.attempt_id,
                    attempt_content_sha256=existing.content_sha256,
                )
                if not self.latest_path(job.job_id).exists():
                    self._commit_bytes(
                        self.latest_path(job.job_id), _model_bytes(pointer), "pointer"
                    )
                return existing
            if existing.job.status in {
                ReanalysisJobStatus.SUCCEEDED,
                ReanalysisJobStatus.NO_ACTION,
                ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED,
            }:
                raise ReanalysisJobStoreError(
                    "deterministic execution identity already has conflicting terminal content"
                )

        self._persist_artifacts(job, artifacts)

        attempts = self._attempts(job.job_id)
        attempt_number = max((attempt.attempt_number for attempt in attempts), default=0) + 1
        attempt = ReanalysisJobAttemptV1.build(job=job, attempt_number=attempt_number)
        self._commit_bytes(
            self.attempt_path(attempt.attempt_id), _model_bytes(attempt), "job"
        )
        pointer = ReanalysisJobPointerV1.build(
            job_id=job.job_id,
            attempt_id=attempt.attempt_id,
            attempt_content_sha256=attempt.content_sha256,
        )
        self._commit_bytes(self.latest_path(job.job_id), _model_bytes(pointer), "pointer")
        return attempt

    def _persist_artifacts(
        self, job: ReanalysisJobV1, artifacts: ReanalysisArtifactBundle | None
    ) -> None:
        for kind, artifact_id, artifact, expected_hash in self._artifact_specs(job, artifacts):
            if not artifact_id or not expected_hash:
                raise ReanalysisJobStoreError("successful job is missing an artifact reference")
            actual_hash = _model_sha256(artifact)
            if actual_hash != expected_hash:
                raise ReanalysisJobStoreError(
                    f"{kind} artifact hash does not match the execution job reference"
                )
            self._commit_bytes(
                self.artifact_path(kind, artifact_id), _model_bytes(artifact), "artifact"
            )

    def load_artifact(
        self,
        kind: ArtifactKind,
        artifact_id: str,
        model_type: type[ModelT],
        expected_sha256: str,
    ) -> ModelT:
        artifact = self._read_model(self.artifact_path(kind, artifact_id), model_type)
        actual_hash = _model_sha256(artifact)
        if actual_hash != expected_sha256:
            raise ReanalysisJobStoreError(
                f"{kind} artifact {artifact_id!r} failed its persisted hash check"
            )
        return artifact

    def load_success_artifacts(self, job: ReanalysisJobV1) -> ReanalysisArtifactBundle:
        """Load every output referenced by a successful job and revalidate lineage."""

        if job.status is not ReanalysisJobStatus.SUCCEEDED:
            raise ReanalysisJobStoreError("only successful jobs have output artifacts")
        normalized = self.load_artifact(
            "normalized-input",
            job.normalized_input_sha256 or "",
            NormalizedCompanyInput,
            job.normalized_input_sha256 or "",
        )
        analysis = self.load_artifact(
            "analysis", job.analysis_id or "", CompanyAnalysis, job.analysis_sha256 or ""
        )
        trace = self.load_artifact(
            "trace", job.trace_id or "", DecisionTrace, job.trace_sha256 or ""
        )
        surface = self.load_artifact(
            "surface",
            job.surface_id or "",
            ResearchSurfaceSnapshotV1,
            job.surface_sha256 or "",
        )
        session = None
        report = None
        if job.research_session_id is not None:
            session = self.load_artifact(
                "research-session",
                job.research_session_id,
                ResearchSession,
                job.research_session_sha256 or "",
            )
        if job.report_id is not None:
            report = self.load_artifact(
                "report", job.report_id, ResearchReport, job.report_sha256 or ""
            )
        if (
            normalized.analysis_id != analysis.analysis_id
            or _listing_identity(normalized.company.primary_listing)
            != _listing_identity(job.listing_id)
            or normalized.profile_id != job.profile_id
            or normalized.as_of != job.execution_as_of.date()
        ):
            raise ReanalysisJobStoreError(
                "normalized input does not match the execution job lineage"
            )
        if (
            analysis.analysis_id != job.analysis_id
            or analysis.as_of != job.execution_as_of.date()
            or _listing_identity(analysis.company.primary_listing)
            != _listing_identity(job.listing_id)
            or analysis.profile_id != normalized.profile_id
        ):
            raise ReanalysisJobStoreError("analysis output does not match the execution job")
        if trace.analysis_id != analysis.analysis_id or surface.analysis_id != analysis.analysis_id:
            raise ReanalysisJobStoreError("execution output lineage does not match analysis")
        if report is not None and report.analysis.analysis_id != analysis.analysis_id:
            raise ReanalysisJobStoreError("research report does not match analysis")
        references = {item.artifact_type: item for item in surface.source_artifacts}
        if (
            references.get("COMPANY_ANALYSIS") is None
            or references["COMPANY_ANALYSIS"].content_sha256 != job.analysis_sha256
        ):
            raise ReanalysisJobStoreError("surface analysis reference does not match the job")
        if (
            references.get("DECISION_TRACE") is None
            or references["DECISION_TRACE"].content_sha256 != job.trace_sha256
        ):
            raise ReanalysisJobStoreError("surface trace reference does not match the job")
        if job.impact.value == "FULL_REANALYSIS":
            if session is None or report is None:
                raise ReanalysisJobStoreError("full execution is missing research artifacts")
            if (
                references.get("RESEARCH_REPORT") is None
                or references["RESEARCH_REPORT"].content_sha256 != job.report_sha256
            ):
                raise ReanalysisJobStoreError("surface report reference does not match the job")
        elif session is not None or report is not None:
            raise ReanalysisJobStoreError("partial execution contains research artifacts")
        return ReanalysisArtifactBundle(
            normalized_input=normalized,
            analysis=analysis,
            trace=trace,
            surface=surface,
            research_session=session,
            report=report,
        )


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _listing_identity(value: str) -> str:
    text = value.strip().upper()
    if "." in text:
        code, market = text.rsplit(".", 1)
        if market in {"SH", "SZ", "HK"}:
            return f"{market}{code}"
    return text


__all__ = [
    "FailureInjector",
    "ReanalysisArtifactBundle",
    "ReanalysisJobStore",
    "ReanalysisJobStoreError",
]
