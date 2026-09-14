"""Injected analyst interfaces and deterministic scripted clients."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, TypeAlias

from pydantic import ValidationError

from .contracts import (
    AgentRunMetadata,
    AnalystExecutionMode,
    AnalystRun,
    ResearchFinding,
    ResearchTask,
)


class AnalystClientError(RuntimeError):
    """Raised when an injected analyst cannot return a valid typed proposal."""


class AnalystClient(Protocol):
    """Vendor-neutral synchronous boundary for one bounded research task."""

    def analyze(self, task: ResearchTask) -> AnalystRun | ResearchFinding | Mapping[str, object]:
        """Return a typed run/finding or a JSON-compatible finding object."""


AnalystResponse: TypeAlias = AnalystRun | ResearchFinding | Mapping[str, object]
ScriptedResponse: TypeAlias = AnalystResponse | Callable[[ResearchTask], AnalystResponse]


def coerce_analyst_response(
    task: ResearchTask,
    response: AnalystResponse,
    *,
    default_metadata: AgentRunMetadata | None = None,
) -> AnalystRun:
    """Turn an external response into a fresh, task-bound deterministic run.

    A response's claimed run ID and hashes are not trusted.  The finding and
    safe metadata are validated, then the repository derives the persisted run
    identity from the exact task and output content.
    """

    try:
        if isinstance(response, AnalystRun):
            finding = response.finding
            metadata = response.metadata
        elif isinstance(response, ResearchFinding):
            finding = response
            metadata = default_metadata
        elif isinstance(response, Mapping):
            payload = dict(response)
            if "finding" in payload:
                raw_finding = payload.pop("finding")
            else:
                raw_finding = dict(payload)
                raw_finding.pop("metadata", None)
            if not isinstance(raw_finding, (ResearchFinding, Mapping)):
                raise TypeError("analyst response finding must be a JSON object")
            finding = (
                raw_finding
                if isinstance(raw_finding, ResearchFinding)
                else ResearchFinding.model_validate(raw_finding)
            )
            raw_metadata = payload.get("metadata")
            if raw_metadata is None:
                metadata = default_metadata
            elif isinstance(raw_metadata, AgentRunMetadata):
                metadata = raw_metadata
            else:
                metadata = AgentRunMetadata.model_validate(raw_metadata)
        else:
            raise TypeError("analyst response must be an AnalystRun, ResearchFinding or object")
        run = AnalystRun.build(task, finding, metadata)
        run.validate_against_task(task)
        return run
    except (TypeError, ValueError, ValidationError) as exc:
        raise AnalystClientError(
            f"invalid analyst response for task {task.task_id}: {exc}"
        ) from exc


class ScriptedAnalystClient:
    """Deterministic response map used by ordinary tests and frozen evaluations."""

    def __init__(
        self, responses: Mapping[str, ScriptedResponse] | Callable[[ResearchTask], AnalystResponse]
    ):
        if not isinstance(responses, Mapping) and not callable(responses):
            raise TypeError("responses must be a mapping or callable")
        self._responses = responses
        self.tasks: list[ResearchTask] = []

    @property
    def calls(self) -> tuple[ResearchTask, ...]:
        """Return an immutable view of tasks sent to this client."""

        return tuple(self.tasks)

    def analyze(self, task: ResearchTask) -> AnalystRun:
        self.tasks.append(task)
        if callable(self._responses):
            response = self._responses(task)
        else:
            if task.task_id not in self._responses:
                raise AnalystClientError(f"no scripted response for task {task.task_id}")
            response = self._responses[task.task_id]
        if callable(response):
            response = response(task)
        try:
            metadata = AgentRunMetadata(
                execution_mode=AnalystExecutionMode.SCRIPTED,
                provider_id="scripted",
                model_id="frozen-script",
            )
            return coerce_analyst_response(task, response, default_metadata=metadata)
        except AnalystClientError:
            raise
        except Exception as exc:
            raise AnalystClientError(
                f"scripted analyst response failed for task {task.task_id}: {exc}"
            ) from exc


class CallableAnalystClient:
    """Small adapter for an external runtime callback without a vendor SDK."""

    def __init__(self, callback: Callable[[ResearchTask], AnalystResponse]):
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._callback = callback

    def analyze(self, task: ResearchTask) -> AnalystRun:
        try:
            response = self._callback(task)
            return coerce_analyst_response(task, response)
        except AnalystClientError:
            raise
        except Exception as exc:
            raise AnalystClientError(
                f"external analyst callback failed for task {task.task_id}: {exc}"
            ) from exc


__all__ = [
    "AnalystClient",
    "AnalystClientError",
    "AnalystResponse",
    "CallableAnalystClient",
    "ScriptedAnalystClient",
    "coerce_analyst_response",
]
