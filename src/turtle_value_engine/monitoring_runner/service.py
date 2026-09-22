"""Scheduler-neutral, durable Phase 6-D2A unattended runner service.

One invocation equals one scheduler wake.  Under an exclusive single-host
lease it settles any crashed prior state, resumes or creates exactly one
activation intent whose frozen PIT/``as_of`` cannot drift with wall-clock
time, enters the existing Phase 6-D1 boundary, and persists a terminal
receipt binding the activation to the exact D1 cycle result and alert outbox
identities and hashes.  Phase 6-B acquisition, Phase 6-A planning/commit,
Phase 6-C execution and D1 alert semantics stay entirely behind their
existing public boundaries.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from turtle_value_engine.monitoring.canonical import canonical_sha256, normalize_utc
from turtle_value_engine.monitoring.models import WatchlistSpecV1
from turtle_value_engine.monitoring_cycle.contracts import (
    MonitoringAlertBatchV1,
    MonitoringCycleResultV1,
    MonitoringCycleSpecV1,
    MonitoringExecutionCatalogV1,
)
from turtle_value_engine.monitoring_cycle.service import MonitoringCycleOutcome
from turtle_value_engine.monitoring_cycle.store import MonitoringCycleStore

from .contracts import (
    RunnerActivationIntentV1,
    RunnerCompletion,
    RunnerConfigV1,
    RunnerReceiptV1,
)
from .lease import LeaseHandle, RunnerLease, RunnerLeaseBusyError
from .store import RunnerStore, RunnerStoreError

RunnerClock = Callable[[], datetime]
WatchlistLoader = Callable[[], WatchlistSpecV1]


class MonitoringRunnerError(ValueError):
    """Base class for D2A runner failures (fail-closed)."""


class RunnerStateConflictError(MonitoringRunnerError):
    """Raised when persisted runner state is ambiguous or conflicting."""


class RunnerArtifactCorruptError(MonitoringRunnerError):
    """Raised when a persisted runner artifact cannot be validated."""


class ActivationRequestConflictError(MonitoringRunnerError):
    """Raised when a resumed activation no longer matches its inputs."""


class UnattendedCycleBoundary(Protocol):
    def run_cycle(
        self, spec: MonitoringCycleSpecV1, watchlist: WatchlistSpecV1
    ) -> MonitoringCycleOutcome:
        """Enter the existing Phase 6-D1 synchronous cycle boundary."""


@dataclass(frozen=True, slots=True)
class RunnerRunOutcome:
    """Terminal result of one unattended runner invocation."""

    classification: RunnerCompletion
    activation: RunnerActivationIntentV1
    receipt: RunnerReceiptV1
    result: MonitoringCycleResultV1
    alert_batch: MonitoringAlertBatchV1
    reused_terminal: bool


def _load_execution_catalog(path: str | None) -> MonitoringExecutionCatalogV1:
    if path is None:
        return MonitoringExecutionCatalogV1.build()
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return MonitoringExecutionCatalogV1.model_validate(payload)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise MonitoringRunnerError(
            f"RUNNER_INVALID_EXECUTION_CATALOG: cannot load {path}: {exc}"
        ) from exc


def resolve_runner_spec(
    config: RunnerConfigV1,
    watchlist: WatchlistSpecV1,
    catalog: MonitoringExecutionCatalogV1,
    *,
    clock: RunnerClock,
    adapter_version: str,
) -> MonitoringCycleSpecV1:
    """Freeze one explicit D1 request, resolving the PIT and window now."""

    as_of = config.as_of if config.as_of is not None else normalize_utc(clock())
    if config.published_from is not None and config.published_to is not None:
        published_from: date = config.published_from
        published_to: date = config.published_to
    else:
        window_days = config.window_days
        if window_days is None:
            raise MonitoringRunnerError(
                "RUNNER_INVALID_CONFIG: acquisition window must be explicit"
            )
        published_to = as_of.date()
        published_from = published_to - timedelta(days=window_days - 1)
    return MonitoringCycleSpecV1.build(
        watchlist_id=watchlist.watchlist_id,
        watchlist_content_sha256=watchlist.content_sha256,
        as_of=as_of,
        acquisition_policy_id=config.acquisition_policy_id,
        source_id=config.source_id,
        adapter_version=adapter_version,
        published_from=published_from,
        published_to=published_to,
        acquisition_limit=config.acquisition_limit,
        network_allowed=config.network_allowed,
        offline_replay=config.offline_replay,
        monitoring_workspace_root=config.monitoring_workspace_root,
        reanalysis_job_root=config.reanalysis_job_root,
        cycle_store_root=config.cycle_store_root,
        execution_catalog=catalog,
    )


def request_fingerprint(
    config: RunnerConfigV1,
    watchlist: WatchlistSpecV1,
    spec: MonitoringCycleSpecV1,
) -> str:
    """Hash every explicit input needed to reproduce the same D1 invocation."""

    return canonical_sha256(
        {
            "domain": "tve-monitoring-runner-request-v1",
            "spec": spec.canonical_payload(),
            "watchlist": watchlist.canonical_payload(),
            "acquisition": {
                "cache_dir": config.cache_dir,
                "timeout_seconds": config.timeout_seconds,
                "max_response_bytes": config.max_response_bytes,
            },
        }
    )


@dataclass(frozen=True, slots=True)
class _Resume:
    intent: RunnerActivationIntentV1


@dataclass(frozen=True, slots=True)
class _Reuse:
    intent: RunnerActivationIntentV1
    receipt: RunnerReceiptV1


@dataclass(frozen=True, slots=True)
class _Fresh:
    intent: RunnerActivationIntentV1


class MonitoringRunnerService:
    """One durable unattended activation around the unchanged D1 boundary."""

    def __init__(
        self,
        *,
        config: RunnerConfigV1,
        store: RunnerStore,
        cycle_store: MonitoringCycleStore,
        lease: RunnerLease,
        d1: UnattendedCycleBoundary,
        watchlist_loader: WatchlistLoader,
        adapter_version: str | None = None,
        clock: RunnerClock | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.cycle_store = cycle_store
        self.lease = lease
        self.d1 = d1
        self.watchlist_loader = watchlist_loader
        self.adapter_version = adapter_version or config.adapter_version
        if not self.adapter_version:
            raise MonitoringRunnerError(
                "RUNNER_MISSING_ADAPTER_VERSION: resolve an explicit adapter version"
            )
        self.clock: RunnerClock = clock or (lambda: datetime.now(UTC))

    def run(self) -> RunnerRunOutcome:
        self.lease.validate_record()
        try:
            with self.lease.held() as handle:
                return self._run_under_lease(handle)
        except RunnerLeaseBusyError:
            raise
        except RunnerStoreError as exc:
            raise RunnerArtifactCorruptError(f"RUNNER_ARTIFACT_CORRUPT: {exc}") from exc

    def _run_under_lease(self, handle: LeaseHandle) -> RunnerRunOutcome:
        resolved = self._settle_and_resolve()
        if isinstance(resolved, _Reuse):
            terminal = self._load_d1_terminal(resolved.intent.spec.cycle_id)
            if terminal is None:
                raise RunnerStateConflictError(
                    "RUNNER_STATE_CONFLICT: terminal receipt has no D1 terminal pair"
                )
            result, alert_batch = terminal
            self.store.publish_receipt(resolved.receipt)
            self.store.clear_active(resolved.intent.runner_id)
            return RunnerRunOutcome(
                classification=RunnerCompletion.COMPLETED_REUSED,
                activation=resolved.intent,
                receipt=resolved.receipt,
                result=result,
                alert_batch=alert_batch,
                reused_terminal=True,
            )

        if isinstance(resolved, _Resume):
            activation = resolved.intent
            base = RunnerCompletion.COMPLETED_RESUMED
            watchlist = self._load_watchlist()
            self._verify_fingerprint(activation, watchlist)
        else:
            watchlist = self._load_watchlist()
            activation = resolved.intent
            base = RunnerCompletion.COMPLETED_NEW

        handle.record(activation.activation_id)

        terminal = self._load_d1_terminal(activation.spec.cycle_id)
        if terminal is not None:
            # D1 already published its terminal pair (a crash happened after
            # D1 terminal but before the runner receipt): repair the runner
            # layer without repeating any provider, model or re-analysis work.
            result, alert_batch = terminal
            reused = True
        else:
            outcome = self.d1.run_cycle(activation.spec, watchlist)
            result = outcome.result
            alert_batch = outcome.alert_batch
            reused = False

        receipt = RunnerReceiptV1.build(
            runner_id=activation.runner_id,
            activation_id=activation.activation_id,
            cycle_id=activation.spec.cycle_id,
            d1_status=result.status.value,
            d1_failure_code=None if result.failure_code is None else result.failure_code.value,
            result_content_sha256=result.content_sha256,
            alert_batch_id=alert_batch.alert_batch_id,
            alert_batch_content_sha256=alert_batch.content_sha256,
            completed_at=self.clock(),
        )
        self.store.publish_receipt(receipt)
        self.store.clear_active(activation.runner_id)
        classification = RunnerCompletion.COMPLETED_REPAIRED if reused else base
        return RunnerRunOutcome(
            classification=classification,
            activation=activation,
            receipt=receipt,
            result=result,
            alert_batch=alert_batch,
            reused_terminal=reused,
        )

    def _settle_and_resolve(self) -> _Resume | _Reuse | _Fresh:
        """Repair crashed pointers, then find or create this wake's intent."""

        runner_id = self.config.runner_id
        latest = self.store.load_latest(runner_id)
        if latest is not None:
            receipt = self.store.load_receipt(latest.activation_id)
            if receipt is None or receipt.content_sha256 != latest.receipt_content_sha256:
                raise RunnerStateConflictError(
                    "RUNNER_STATE_CONFLICT: latest pointer does not bind a valid receipt"
                )

        active = self.store.load_active(runner_id)
        unfinished = self.store.list_unfinished_activations(runner_id)
        if len(unfinished) > 1:
            raise RunnerStateConflictError(
                "RUNNER_STATE_CONFLICT: multiple unfinished activations for one runner"
            )

        if active is not None:
            intent = self.store.load_intent(active.activation_id)
            if intent.content_sha256 != active.intent_content_sha256:
                raise RunnerStateConflictError(
                    "RUNNER_STATE_CONFLICT: active pointer does not bind its intent"
                )
            if intent.activation_id in {item.activation_id for item in unfinished}:
                return _Resume(intent=intent)
            # The active activation already has a receipt: a crash happened
            # between publishing it and clearing the slot.  Settle the slot
            # and continue with this wake's own activation.
            self._settle_finished(runner_id, intent.activation_id)
            active = None

        if unfinished:
            # A crash persisted the intent before the active pointer moved.
            # Adopt it so the retry resumes the same frozen PIT instead of
            # deriving a new cycle from a later wall clock.
            intent = unfinished[0]
            self.store.set_active(intent)
            return _Resume(intent=intent)

        watchlist = self._load_watchlist()
        catalog = _load_execution_catalog(self.config.execution_catalog_path)
        spec = resolve_runner_spec(
            self.config,
            watchlist,
            catalog,
            clock=self.clock,
            adapter_version=self.adapter_version,
        )
        intent = RunnerActivationIntentV1.build(
            runner_id=runner_id,
            created_at=self.clock(),
            request_fingerprint=request_fingerprint(self.config, watchlist, spec),
            spec=spec,
        )
        existing_receipt = self.store.load_receipt(intent.activation_id)
        if existing_receipt is not None:
            # The scheduler woke again with byte-identical request inputs;
            # the finished activation is reused without any new D1 work.
            return _Reuse(intent=intent, receipt=existing_receipt)
        self.store.save_intent(intent)
        self.store.set_active(intent)
        return _Fresh(intent=intent)

    def _settle_finished(self, runner_id: str, activation_id: str) -> None:
        receipt = self.store.load_receipt(activation_id)
        if receipt is None:
            raise RunnerStateConflictError(
                "RUNNER_STATE_CONFLICT: finished activation has no receipt"
            )
        self.store.publish_receipt(receipt)
        self.store.clear_active(runner_id)

    def _load_watchlist(self) -> WatchlistSpecV1:
        try:
            return self.watchlist_loader()
        except MonitoringRunnerError:
            raise
        except Exception as exc:
            raise MonitoringRunnerError(
                f"RUNNER_WATCHLIST_UNAVAILABLE: cannot load watchlist: {exc}"
            ) from exc

    def _verify_fingerprint(
        self, activation: RunnerActivationIntentV1, watchlist: WatchlistSpecV1
    ) -> None:
        if (
            activation.spec.watchlist_id != watchlist.watchlist_id
            or activation.spec.watchlist_content_sha256 != watchlist.content_sha256
        ):
            raise ActivationRequestConflictError(
                "RUNNER_ACTIVATION_CONFLICT: the watchlist no longer matches the "
                "unfinished activation; resolve the conflict explicitly"
            )
        current = request_fingerprint(self.config, watchlist, activation.spec)
        if current != activation.request_fingerprint:
            raise ActivationRequestConflictError(
                "RUNNER_ACTIVATION_CONFLICT: runner inputs changed under the "
                "unfinished activation; resolve the conflict explicitly"
            )

    def _load_d1_terminal(
        self, cycle_id: str
    ) -> tuple[MonitoringCycleResultV1, MonitoringAlertBatchV1] | None:
        try:
            return self.cycle_store.load_terminal(cycle_id)
        except Exception as exc:
            raise RunnerArtifactCorruptError(
                f"RUNNER_D1_TERMINAL_CORRUPT: cannot validate D1 terminal artifacts: {exc}"
            ) from exc


__all__ = [
    "ActivationRequestConflictError",
    "MonitoringRunnerError",
    "MonitoringRunnerService",
    "RunnerArtifactCorruptError",
    "RunnerClock",
    "RunnerRunOutcome",
    "RunnerStateConflictError",
    "RunnerLeaseBusyError",
    "UnattendedCycleBoundary",
    "request_fingerprint",
    "resolve_runner_spec",
]
