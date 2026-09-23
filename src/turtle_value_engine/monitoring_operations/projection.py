"""Deterministic read-only projection over the configured Phase 6 monitoring chain.

This module performs strictly observational reads: it never invokes a
provider, acquisition adapter, analyst/model, research orchestrator, D1 cycle
execution, re-analysis executor, delivery transport, retry/resend, pointer
repair/publication or acknowledgement, and it never writes to any store.
Only already-proven read-only helpers are used; helpers with hidden
repair/write behaviour (for example ``MonitoringCycleStore.load_terminal``
with its default repair flag or the delivery service's validating repair
path) are deliberately not called.

Corrupt, foreign or contradictory store evidence fails closed with a stable
machine-readable error whose message never embeds local paths or secret
material from the underlying exception.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from turtle_value_engine.monitoring import WatchlistSpecV1
from turtle_value_engine.monitoring.workspace import (
    MonitoringWorkspace,
    MonitoringWorkspaceError,
)
from turtle_value_engine.monitoring_cycle.store import (
    MonitoringCycleStore,
    MonitoringCycleStoreError,
)
from turtle_value_engine.monitoring_delivery import (
    DeliveryLedgerError,
    DeliveryLedgerStore,
    delivery_status_projection,
)
from turtle_value_engine.monitoring_delivery.service import MonitoringDeliveryError
from turtle_value_engine.monitoring_execution.store import (
    ReanalysisJobStore,
    ReanalysisJobStoreError,
)
from turtle_value_engine.monitoring_runner import RunnerLease, RunnerStore
from turtle_value_engine.monitoring_runner.lease import RunnerLeaseError
from turtle_value_engine.monitoring_runner.store import RunnerStoreError

from .contracts import (
    MonitoringOperationsActivationV1,
    MonitoringOperationsCycleV1,
    MonitoringOperationsDeliveryAttemptV1,
    MonitoringOperationsDeliveryV1,
    MonitoringOperationsJobDetailV1,
    MonitoringOperationsJobV1,
    MonitoringOperationsLeaseRecordV1,
    MonitoringOperationsProjectionV1,
    MonitoringOperationsReceiptV1,
    MonitoringOperationsRunnerV1,
    MonitoringOperationsSourcesV1,
    MonitoringOperationsUnresolvedClaimV1,
)


class MonitoringOperationsError(ValueError):
    """Base fail-closed error with a stable machine-readable code."""

    code: ClassVar[str] = "MONITORING_OPERATIONS_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(message)


class MonitoringOperationsSourcesError(MonitoringOperationsError):
    """The explicit source binding itself is unusable (configuration error)."""

    code = "MONITORING_OPERATIONS_SOURCES_INVALID"


class MonitoringOperationsConflictError(MonitoringOperationsError):
    """Store evidence is corrupt, foreign or contradictory; nothing is hidden."""

    code = "MONITORING_OPERATIONS_CONFLICT"


_STORE_ERRORS = (
    MonitoringWorkspaceError,
    RunnerStoreError,
    RunnerLeaseError,
    MonitoringCycleStoreError,
    ReanalysisJobStoreError,
    MonitoringDeliveryError,
    DeliveryLedgerError,
)


def _conflict(exc: Exception) -> MonitoringOperationsConflictError:
    # Only the exception *type* is surfaced: underlying messages may embed
    # local absolute paths, which must never reach an API/browser payload.
    return MonitoringOperationsConflictError(
        "monitoring source evidence failed closed validation "
        f"({type(exc).__name__}); no projection was fabricated"
    )


def _load_watchlist(path: str) -> WatchlistSpecV1:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MonitoringOperationsSourcesError(
            "the configured watchlist file could not be read as JSON "
            f"({type(exc).__name__})"
        ) from exc
    try:
        if not isinstance(payload, dict):
            raise TypeError("watchlist payload is not a JSON object")
        return WatchlistSpecV1.build(**payload)
    except Exception as exc:
        raise MonitoringOperationsSourcesError(
            "the configured watchlist file failed validation "
            f"({type(exc).__name__})"
        ) from exc


def build_monitoring_operations_projection(
    sources: MonitoringOperationsSourcesV1,
) -> MonitoringOperationsProjectionV1:
    """Project the configured runner's current operational chain, read-only."""

    if not isinstance(sources, MonitoringOperationsSourcesV1):
        raise TypeError("sources must be a MonitoringOperationsSourcesV1")
    watchlist = _load_watchlist(sources.watchlist_path)
    try:
        return _build(sources, watchlist)
    except _STORE_ERRORS as exc:
        raise _conflict(exc) from exc
    except OSError as exc:
        raise _conflict(exc) from exc


def _build(
    sources: MonitoringOperationsSourcesV1, watchlist: WatchlistSpecV1
) -> MonitoringOperationsProjectionV1:
    workspace = MonitoringWorkspace(sources.monitoring_workspace_root)
    status = workspace.status(watchlist.watchlist_id)

    runner_store = RunnerStore(sources.runner_root)
    lease = RunnerLease(
        sources.runner_root,
        sources.runner_id,
        ttl_seconds=sources.lease_ttl_seconds,
    )
    probe = lease.probe()
    latest = runner_store.load_latest(sources.runner_id)
    active = runner_store.load_active(sources.runner_id)
    unfinished = runner_store.list_unfinished_activations(sources.runner_id)

    runner = MonitoringOperationsRunnerV1(
        runner_id=sources.runner_id,
        lease_state=probe["state"],
        lease_corrupt=bool(probe["corrupt"]),
        lease_record=None
        if probe["record"] is None
        else MonitoringOperationsLeaseRecordV1.model_validate(probe["record"]),
        unfinished_activation_ids=[intent.activation_id for intent in unfinished],
        latest_terminal_activation_id=None if latest is None else latest.activation_id,
    )

    activation = _project_activation(runner_store, latest=latest, active=active)
    cycle = None
    jobs: list[MonitoringOperationsJobV1] = []
    if activation is not None:
        cycle, jobs = _project_cycle_and_jobs(sources, activation.cycle_id)
    deliveries = _project_deliveries(sources, activation)

    return MonitoringOperationsProjectionV1(
        runner_id=sources.runner_id,
        watchlist=status,
        runner=runner,
        activation=activation,
        cycle=cycle,
        jobs=jobs,
        deliveries_configured=sources.delivery_root is not None,
        deliveries=deliveries,
    )


def _project_activation(
    runner_store: RunnerStore, *, latest, active
) -> MonitoringOperationsActivationV1 | None:
    if active is not None:
        intent = runner_store.load_intent(active.activation_id)
        if intent.content_sha256 != active.intent_content_sha256:
            raise MonitoringOperationsConflictError(
                "the runner active pointer does not match its activation intent"
            )
        if runner_store.receipt_exists(active.activation_id):
            raise MonitoringOperationsConflictError(
                "an active runner pointer coexists with a terminal receipt"
            )
        return MonitoringOperationsActivationV1(
            kind="ACTIVE",
            activation_id=intent.activation_id,
            runner_id=intent.runner_id,
            cycle_id=intent.spec.cycle_id,
            as_of=intent.spec.as_of,
            created_at=intent.created_at,
            request_fingerprint=intent.request_fingerprint,
            intent_content_sha256=intent.content_sha256,
            receipt=None,
        )
    if latest is None:
        return None
    intent = runner_store.load_intent(latest.activation_id)
    receipt = runner_store.load_receipt(latest.activation_id)
    if receipt is None:
        raise MonitoringOperationsConflictError(
            "the runner latest pointer names an activation without a receipt"
        )
    if receipt.content_sha256 != latest.receipt_content_sha256:
        raise MonitoringOperationsConflictError(
            "the runner latest pointer does not match its terminal receipt"
        )
    if receipt.cycle_id != intent.spec.cycle_id or receipt.runner_id != intent.runner_id:
        raise MonitoringOperationsConflictError(
            "the terminal receipt contradicts its activation intent"
        )
    return MonitoringOperationsActivationV1(
        kind="LATEST_TERMINAL",
        activation_id=intent.activation_id,
        runner_id=intent.runner_id,
        cycle_id=intent.spec.cycle_id,
        as_of=intent.spec.as_of,
        created_at=intent.created_at,
        request_fingerprint=intent.request_fingerprint,
        intent_content_sha256=intent.content_sha256,
        receipt=MonitoringOperationsReceiptV1(
            classification=receipt.classification,
            d1_status=receipt.d1_status,
            d1_failure_code=receipt.d1_failure_code,
            result_content_sha256=receipt.result_content_sha256,
            alert_batch_id=receipt.alert_batch_id,
            alert_batch_content_sha256=receipt.alert_batch_content_sha256,
            completed_at=receipt.completed_at,
            content_sha256=receipt.content_sha256,
        ),
    )


def _project_cycle_and_jobs(
    sources: MonitoringOperationsSourcesV1, cycle_id: str
) -> tuple[MonitoringOperationsCycleV1 | None, list[MonitoringOperationsJobV1]]:
    cycle_store = MonitoringCycleStore(sources.cycle_store_root)
    # ``load_status`` always reads with ``repair_pointer=False``: no write.
    status = cycle_store.load_status(cycle_id)
    if status is None:
        return None, []
    result = status["cycle"]
    alerts = status["alert_batch"]
    cycle = MonitoringOperationsCycleV1(
        cycle_id=result.cycle_id,
        status=result.status,
        failure_code=None if result.failure_code is None else result.failure_code.value,
        message=result.message,
        as_of=result.as_of,
        watchlist_id=result.watchlist_id,
        monitoring_run_id=result.monitoring_run_id,
        event_batch_id=result.event_batch_id,
        next_state_id=result.next_state_id,
        alert_batch_id=result.alert_batch_id,
        alert_batch_content_sha256=result.alert_batch_content_sha256,
        result_content_sha256=result.content_sha256,
        pointer_published=bool(status["pointer_published"]),
        alert_count=len(alerts.alerts),
        alerts=list(alerts.alerts),
    )
    job_store = ReanalysisJobStore(sources.reanalysis_job_root)
    jobs: list[MonitoringOperationsJobV1] = []
    for disposition in result.execution:
        attempt = job_store.load_latest(disposition.job_id)
        detail = None
        if attempt is not None:
            job = attempt.job
            detail = MonitoringOperationsJobDetailV1(
                status=job.status,
                failure_code=None if job.failure_code is None else job.failure_code.value,
                message=job.message,
                attempt_number=attempt.attempt_number,
                evidence_codes=list(job.evidence_codes),
                analysis_id=job.analysis_id,
                analysis_sha256=job.analysis_sha256,
                surface_id=job.surface_id,
                surface_sha256=job.surface_sha256,
            )
        jobs.append(
            MonitoringOperationsJobV1(
                request_id=disposition.request_id,
                listing_id=disposition.listing_id,
                impact=disposition.impact,
                job_id=disposition.job_id,
                job_content_sha256=disposition.job_content_sha256,
                disposition_status=disposition.status,
                disposition_failure_code=disposition.failure_code,
                resolution=disposition.resolution,
                job=detail,
            )
        )
    return cycle, jobs


def _project_deliveries(
    sources: MonitoringOperationsSourcesV1,
    activation: MonitoringOperationsActivationV1 | None,
) -> list[MonitoringOperationsDeliveryV1]:
    if sources.delivery_root is None or activation is None:
        return []
    ledger = DeliveryLedgerStore(sources.delivery_root)
    # ``delivery_status_projection`` is the proven read-only boundary: it
    # validates the published pointer truthfully and never repairs anything.
    # Only the bounded per-delivery entries are projected; the helper's local
    # ``delivery_root`` echo never leaves this module.
    projection = delivery_status_projection(ledger, activation_id=activation.activation_id)
    deliveries: list[MonitoringOperationsDeliveryV1] = []
    for entry in projection["deliveries"]:
        deliveries.append(
            MonitoringOperationsDeliveryV1(
                delivery_id=entry["delivery_id"],
                runner_id=entry["runner_id"],
                activation_id=entry["activation_id"],
                cycle_id=entry["cycle_id"],
                alert_batch_id=entry["alert_batch_id"],
                destination_id=entry["destination_id"],
                transport=entry["transport"],
                payload_contract=entry["payload_contract"],
                payload_sha256=entry["payload_sha256"],
                empty_outbox=entry["empty_outbox"],
                created_at=entry["created_at"],
                state=entry["state"],
                pointer_published=entry["pointer_published"],
                pointer_status=entry["pointer_status"],
                dispatch_claim_count=entry["dispatch_claim_count"],
                unresolved_claim_numbers=entry["unresolved_claim_numbers"],
                unresolved_dispatch_claim=None
                if entry["unresolved_dispatch_claim"] is None
                else MonitoringOperationsUnresolvedClaimV1.model_validate(
                    entry["unresolved_dispatch_claim"]
                ),
                attempts=[
                    MonitoringOperationsDeliveryAttemptV1.model_validate(attempt)
                    for attempt in entry["attempts"]
                ],
            )
        )
    return deliveries


__all__ = [
    "MonitoringOperationsConflictError",
    "MonitoringOperationsError",
    "MonitoringOperationsSourcesError",
    "build_monitoring_operations_projection",
]
