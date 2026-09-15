"""Injected analyst interfaces and deterministic scripted clients."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import Event, Thread
from typing import Protocol, TypeAlias

from pydantic import ValidationError

from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    AgentRunMetadata,
    AnalystExecutionMode,
    AnalystRun,
    ResearchFinding,
    ResearchTask,
)


class AnalystClientError(RuntimeError):
    """Raised when an injected analyst cannot return a valid typed proposal."""


def _validate_task_budget(task: ResearchTask) -> None:
    """Enforce the task envelope before invoking an external runtime."""

    context_items = (
        len(task.packet.evidence)
        + len(task.packet.facts)
        + len(task.packet.deterministic_metrics)
        + len(task.context_findings)
    )
    if context_items > task.max_context_items:
        raise AnalystClientError(
            f"task {task.task_id} exceeds max_context_items "
            f"({context_items} > {task.max_context_items})"
        )


def _response_size(response: AnalystResponse) -> int:
    """Return the canonical serialized response size before Pydantic coercion."""

    if isinstance(response, (AnalystRun, ResearchFinding)):
        payload = response.model_dump(mode="json", warnings=False)
    elif isinstance(response, Mapping):
        payload = dict(response)
    else:
        raise AnalystClientError("analyst response must be a typed object or JSON object")
    try:
        return len(canonical_json_bytes(payload))
    except (TypeError, ValueError) as exc:
        raise AnalystClientError(f"analyst response is not JSON serializable: {exc}") from exc


def _validate_response_budget(task: ResearchTask, response: AnalystResponse) -> None:
    """Reject oversized output at the runtime boundary, before persistence."""

    size = _response_size(response)
    if size > task.max_output_bytes:
        raise AnalystClientError(
            f"analyst response exceeds max_output_bytes ({size} > {task.max_output_bytes})"
        )


def _response_finding(response: AnalystResponse) -> ResearchFinding:
    """Extract and validate the finding needed for claim-budget enforcement."""

    if isinstance(response, AnalystRun):
        return response.finding
    if isinstance(response, ResearchFinding):
        return response
    if isinstance(response, Mapping):
        raw_finding = response.get("finding", response)
        if isinstance(raw_finding, ResearchFinding):
            return raw_finding
        if isinstance(raw_finding, Mapping):
            try:
                return ResearchFinding.model_validate(raw_finding)
            except (TypeError, ValueError, ValidationError) as exc:
                raise AnalystClientError(f"analyst response finding is invalid: {exc}") from exc
    raise AnalystClientError("analyst response must contain a typed research finding")


def _validate_response_claim_budget(task: ResearchTask, response: AnalystResponse) -> None:
    """Reject responses that exceed the task's claim/question limits."""

    finding = _response_finding(response)
    claim_count = len(finding.supporting_claims) + len(finding.counter_evidence_claims)
    if claim_count > task.max_output_claims:
        raise AnalystClientError(
            f"analyst response exceeds max_output_claims "
            f"({claim_count} > {task.max_output_claims})"
        )
    unresolved_count = len(finding.unresolved_questions)
    if unresolved_count > task.max_unresolved_questions:
        raise AnalystClientError(
            f"analyst response exceeds max_unresolved_questions "
            f"({unresolved_count} > {task.max_unresolved_questions})"
        )


def _validate_response_budgets(task: ResearchTask, response: AnalystResponse) -> None:
    _validate_response_budget(task, response)
    _validate_response_claim_budget(task, response)


def _invoke_with_timeout(
    callback: Callable[[ResearchTask], AnalystResponse], task: ResearchTask
) -> AnalystResponse:
    """Run a callback in a daemon thread so a hung runtime fails closed.

    Python cannot safely kill an arbitrary synchronous callback.  The daemon
    boundary therefore stops waiting after the declared budget and never
    persists a late result.  This is sufficient for the injected adapter and
    keeps the deterministic engine independent from runtime implementation.
    """

    _validate_task_budget(task)
    result: list[AnalystResponse] = []
    error: list[BaseException] = []
    completed = Event()

    def run() -> None:
        try:
            result.append(callback(task))
        except BaseException as exc:  # retain callback errors across the thread boundary
            error.append(exc)
        finally:
            completed.set()

    Thread(target=run, daemon=True, name=f"tve-analyst-{task.task_id}").start()
    if not completed.wait(task.timeout_seconds):
        raise AnalystClientError(
            f"analyst task {task.task_id} exceeded timeout_seconds={task.timeout_seconds}"
        )
    if error:
        exc = error[0]
        if isinstance(exc, AnalystClientError):
            raise exc
        raise AnalystClientError(f"analyst callback failed: {exc}") from exc
    if not result:
        raise AnalystClientError("analyst callback returned no response")
    response = result[0]
    _validate_response_budgets(task, response)
    return response


def _runtime_metadata(
    task: ResearchTask,
    *,
    execution_mode: AnalystExecutionMode,
    provider_id: str,
    model_id: str,
) -> AgentRunMetadata:
    """Record the budgets actually enforced by the adapter."""

    return AgentRunMetadata(
        execution_mode=execution_mode,
        provider_id=provider_id,
        model_id=model_id,
        timeout_seconds=task.timeout_seconds,
        max_context_items=task.max_context_items,
        max_output_claims=task.max_output_claims,
        max_unresolved_questions=task.max_unresolved_questions,
        max_output_bytes=task.max_output_bytes,
    )


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
        _validate_task_budget(task)
        if callable(self._responses):
            response = _invoke_with_timeout(self._responses, task)
        else:
            if task.task_id not in self._responses:
                raise AnalystClientError(f"no scripted response for task {task.task_id}")
            response = self._responses[task.task_id]
        if callable(response):
            response = _invoke_with_timeout(response, task)
        else:
            _validate_response_budgets(task, response)
        try:
            metadata = _runtime_metadata(
                task,
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
            response = _invoke_with_timeout(self._callback, task)
            metadata = _runtime_metadata(
                task,
                execution_mode=AnalystExecutionMode.EXTERNAL,
                provider_id="injected-callback",
                model_id="external-runtime",
            )
            return coerce_analyst_response(task, response, default_metadata=metadata)
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
