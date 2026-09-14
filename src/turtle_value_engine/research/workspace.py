"""Filesystem persistence for resumable research artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from turtle_value_engine.models import CompanyAnalysis
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.traceability import DecisionTrace

from .contracts import (
    AnalystRun,
    BusinessQualityResearchResult,
    EvidencePacket,
    ResearchSession,
    ResearchTask,
)
from .report import ResearchReport


class ResearchWorkspaceError(ValueError):
    """Raised when a persisted research artifact is missing or inconsistent."""


ModelT = TypeVar("ModelT", bound=BaseModel)


class ResearchWorkspace:
    """Atomic, JSON-only artifact store shared by external agent runtimes.

    The workspace stores task inputs and typed outputs separately.  It contains
    no model SDK state, credentials or chat transcript; another process can
    resume by reading the session index and the referenced JSON artifacts.
    """

    _KINDS = {
        "packets": EvidencePacket,
        "tasks": ResearchTask,
        "runs": AnalystRun,
        "sessions": ResearchSession,
        "business-quality": BusinessQualityResearchResult,
        "analysis": CompanyAnalysis,
        "trace": DecisionTrace,
        "reports": ResearchReport,
    }

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, kind: str, artifact_id: str) -> Path:
        if kind not in self._KINDS:
            raise ValueError(f"unsupported research artifact kind: {kind!r}")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or "/" in artifact_id
            or "\\" in artifact_id
            or artifact_id in {".", ".."}
        ):
            raise ValueError("artifact_id must be a non-empty path-safe string")
        return self.root / kind / f"{artifact_id}.json"

    def _write(self, kind: str, artifact_id: str, artifact: BaseModel) -> Path:
        path = self.path_for(kind, artifact_id)
        serialized = canonical_json_bytes(artifact.model_dump(mode="json")) + b"\n"
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ResearchWorkspaceError(f"research artifact is not a regular file: {path}")
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise ResearchWorkspaceError(
                    f"cannot read existing research artifact: {exc}"
                ) from exc
            if existing != serialized:
                raise ResearchWorkspaceError(
                    f"research artifact ID {artifact_id!r} already has conflicting content"
                )
            return path

        temporary_path: Path | None = None
        descriptor = -1
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
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
            # link rather than replace: a completed artifact is immutable.
            os.link(temporary_path, path)
            temporary_path.unlink()
            temporary_path = None
        except (OSError, TypeError, ValueError) as exc:
            raise ResearchWorkspaceError(f"cannot persist research artifact {path}: {exc}") from exc
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
        return path

    def _read(self, kind: str, artifact_id: str) -> BaseModel:
        path = self.path_for(kind, artifact_id)
        if path.is_symlink() or not path.is_file():
            raise ResearchWorkspaceError(f"research artifact is missing or not a file: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_number)
            model = self._KINDS[kind].model_validate(payload)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise ResearchWorkspaceError(f"invalid research artifact {path}: {exc}") from exc
        actual_id = _artifact_id(kind, model)
        valid_snapshot = (
            kind in {"analysis", "trace"} and artifact_id.startswith(actual_id + "-")
            if actual_id is not None
            else False
        )
        if actual_id is not None and actual_id != artifact_id and not valid_snapshot:
            raise ResearchWorkspaceError(
                f"research artifact filename does not match its persisted identity: {path}"
            )
        return model

    def save_packet(self, packet: EvidencePacket) -> Path:
        return self._write("packets", packet.packet_id, packet)

    def load_packet(self, packet_id: str) -> EvidencePacket:
        return self._read("packets", packet_id)  # type: ignore[return-value]

    def save_task(self, task: ResearchTask) -> Path:
        return self._write("tasks", task.task_id, task)

    def load_task(self, task_id: str) -> ResearchTask:
        return self._read("tasks", task_id)  # type: ignore[return-value]

    def save_run(self, run: AnalystRun) -> Path:
        return self._write("runs", run.run_id, run)

    def load_run(self, run_id: str) -> AnalystRun:
        return self._read("runs", run_id)  # type: ignore[return-value]

    def save_session(self, session: ResearchSession) -> Path:
        return self._write("sessions", session.session_id, session)

    def load_session(self, session_id: str) -> ResearchSession:
        return self._read("sessions", session_id)  # type: ignore[return-value]

    def save_business_quality(self, result: BusinessQualityResearchResult) -> Path:
        return self._write(
            "business-quality", result.session_id or result.analysis_id, result
        )

    def load_business_quality(self, artifact_id: str) -> BusinessQualityResearchResult:
        """Load a Business Quality result by its session/artifact identity."""

        return self._read("business-quality", artifact_id)  # type: ignore[return-value]

    def save_analysis(self, analysis: CompanyAnalysis) -> Path:
        primary_path = self.path_for("analysis", analysis.analysis_id)
        serialized = canonical_json_bytes(analysis.model_dump(mode="json")) + b"\n"
        if not primary_path.exists():
            return self._write("analysis", analysis.analysis_id, analysis)
        if primary_path.is_symlink() or not primary_path.is_file():
            raise ResearchWorkspaceError(f"research artifact is not a regular file: {primary_path}")
        try:
            if primary_path.read_bytes() == serialized:
                return primary_path
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"cannot read existing research artifact: {exc}"
            ) from exc
        snapshot_id = (
            f"{analysis.analysis_id}-snapshot-{hashlib.sha256(serialized).hexdigest()[:24]}"
        )
        return self._write("analysis", snapshot_id, analysis)

    def load_analysis(self, analysis_id: str) -> CompanyAnalysis:
        primary_path = self.path_for("analysis", analysis_id)
        if primary_path.exists():
            return self._read("analysis", analysis_id)  # type: ignore[return-value]
        candidates = sorted(self.root.joinpath("analysis").glob(f"{analysis_id}-*.json"))
        if len(candidates) != 1:
            raise ResearchWorkspaceError(
                f"expected one analysis artifact for {analysis_id!r}, found {len(candidates)}"
            )
        return self._read("analysis", candidates[0].stem)  # type: ignore[return-value]

    def load_analysis_artifact(self, artifact_id: str) -> CompanyAnalysis:
        """Load a specific analysis snapshot when approvals created variants."""

        return self._read("analysis", artifact_id)  # type: ignore[return-value]

    def save_trace(self, trace: DecisionTrace) -> Path:
        primary_path = self.path_for("trace", trace.analysis_id)
        serialized = canonical_json_bytes(trace.model_dump(mode="json")) + b"\n"
        if not primary_path.exists():
            return self._write("trace", trace.analysis_id, trace)
        if primary_path.is_symlink() or not primary_path.is_file():
            raise ResearchWorkspaceError(f"research artifact is not a regular file: {primary_path}")
        try:
            if primary_path.read_bytes() == serialized:
                return primary_path
        except OSError as exc:
            raise ResearchWorkspaceError(
                f"cannot read existing research artifact: {exc}"
            ) from exc
        snapshot_id = f"{trace.analysis_id}-snapshot-{hashlib.sha256(serialized).hexdigest()[:24]}"
        return self._write("trace", snapshot_id, trace)

    def load_trace(self, analysis_id: str) -> DecisionTrace:
        primary_path = self.path_for("trace", analysis_id)
        if primary_path.exists():
            return self._read("trace", analysis_id)  # type: ignore[return-value]
        candidates = sorted(self.root.joinpath("trace").glob(f"{analysis_id}-*.json"))
        if len(candidates) != 1:
            raise ResearchWorkspaceError(
                f"expected one trace artifact for {analysis_id!r}, found {len(candidates)}"
            )
        return self._read("trace", candidates[0].stem)  # type: ignore[return-value]

    def load_trace_artifact(self, artifact_id: str) -> DecisionTrace:
        """Load a specific trace snapshot when an analysis has variants."""

        return self._read("trace", artifact_id)  # type: ignore[return-value]

    def save_report(self, report: ResearchReport) -> Path:
        return self._write("reports", report.report_id, report)

    def load_report(self, report_id: str) -> ResearchReport:
        return self._read("reports", report_id)  # type: ignore[return-value]


def _artifact_id(kind: str, model: BaseModel) -> str | None:
    if kind == "packets":
        return getattr(model, "packet_id")
    if kind == "tasks":
        return getattr(model, "task_id")
    if kind == "runs":
        return getattr(model, "run_id")
    if kind == "sessions":
        return getattr(model, "session_id")
    if kind == "business-quality":
        return getattr(model, "session_id") or getattr(model, "analysis_id")
    if kind == "analysis":
        return getattr(model, "analysis_id")
    if kind == "trace":
        return getattr(model, "analysis_id")
    if kind == "reports":
        return getattr(model, "report_id")
    return None


def _reject_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


# The shorter store name is useful to runtimes that treat this as an artifact
# repository.  Both names intentionally refer to the same immutable boundary.
ResearchArtifactStore = ResearchWorkspace


__all__ = ["ResearchArtifactStore", "ResearchWorkspace", "ResearchWorkspaceError"]
