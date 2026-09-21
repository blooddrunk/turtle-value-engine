"""Local atomic/idempotent workspace for Phase 6-A monitoring artifacts.

Layout (all JSON, canonical bytes, hash-verified on read)::

    <root>/
      watchlists/<watchlist_id>-<content_sha256[:16]>.json
      event-batches/<batch_id>.json
      runs/<run_id>.json
      states/<state_id>.json
      states/current-<watchlist_id>.json   # atomic pointer

Immutable artifacts are created through ``link(2)`` so an existing identity
with identical bytes is an idempotent no-op and any byte difference fails
closed.  The current-state pointer moves only after every artifact of the
run is durably written (file fsync followed by directory fsync), and the
pointer itself is replaced atomically.  The workspace performs no network,
provider, model or analysis calls.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .canonical import canonical_json_bytes
from .models import (
    MonitoringEventBatchV1,
    MonitoringRunV1,
    MonitoringStatePointerV1,
    MonitoringStatusEntryV1,
    MonitoringStatusV1,
    WatchlistSpecV1,
    WatchlistStateV1,
)

WriteKind = Literal["artifact", "pointer"]
FailureInjector = Callable[[Path, WriteKind], None]


class MonitoringWorkspaceError(ValueError):
    """Raised when a monitoring artifact is missing, corrupt or conflicting."""


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


class MonitoringWorkspace:
    """Atomic, JSON-only monitoring artifact store (no database, no network)."""

    def __init__(self, root: str | Path, *, failure_injector: FailureInjector | None = None):
        self.root = Path(root)
        self._failure_injector = failure_injector

    # -- paths -------------------------------------------------------------

    def watchlist_path(self, watchlist: WatchlistSpecV1) -> Path:
        return (
            self.root
            / "watchlists"
            / f"{watchlist.watchlist_id}-{watchlist.content_sha256[:16]}.json"
        )

    def event_batch_path(self, batch_id: str) -> Path:
        return self.root / "event-batches" / f"{batch_id}.json"

    def run_path(self, run_id: str) -> Path:
        return self.root / "runs" / f"{run_id}.json"

    def state_path(self, state_id: str) -> Path:
        return self.root / "states" / f"{state_id}.json"

    def pointer_path(self, watchlist_id: str) -> Path:
        return self.root / "states" / f"current-{watchlist_id}.json"

    # -- writes ------------------------------------------------------------

    def _inject_failure(self, path: Path, kind: WriteKind) -> None:
        if self._failure_injector is not None:
            self._failure_injector(path, kind)

    def _write_immutable(self, path: Path, content: bytes) -> None:
        """Create an artifact once; identical bytes are idempotent."""

        if path.exists():
            self._verify_regular_file(path)
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise MonitoringWorkspaceError(
                    f"cannot read existing monitoring artifact: {exc}"
                ) from exc
            if existing != content:
                raise MonitoringWorkspaceError(
                    f"monitoring artifact {path.name} already has conflicting content"
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
            # link rather than replace: a committed artifact is immutable.
            os.link(temporary_path, path)
            _fsync_directory(path.parent)
            temporary_path.unlink()
            temporary_path = None
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise MonitoringWorkspaceError(
                    f"cannot read existing monitoring artifact: {exc}"
                ) from exc
            if existing != content:
                raise MonitoringWorkspaceError(
                    f"monitoring artifact {path.name} already has conflicting content"
                )
        except OSError as exc:
            raise MonitoringWorkspaceError(
                f"cannot persist monitoring artifact {path}: {exc}"
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
        """Atomically replace the current-state pointer."""

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
            raise MonitoringWorkspaceError(
                f"cannot update monitoring state pointer {path}: {exc}"
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

    def _commit_bytes(self, path: Path, model_content: bytes, kind: WriteKind) -> None:
        try:
            self._inject_failure(path, kind)
        except OSError as exc:
            raise MonitoringWorkspaceError(
                f"monitoring workspace write failed at {path}: {exc}"
            ) from exc
        if kind == "pointer":
            self._write_pointer(path, model_content)
        else:
            self._write_immutable(path, model_content)

    # -- reads -------------------------------------------------------------

    @staticmethod
    def _verify_regular_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise MonitoringWorkspaceError(
                f"monitoring artifact is missing or not a regular file: {path}"
            )

    def _read_model(self, path: Path, model_cls: type) -> object:
        self._verify_regular_file(path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_number)
            model = model_cls.model_validate(payload)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise MonitoringWorkspaceError(
                f"corrupt or invalid monitoring artifact {path}: {exc}"
            ) from exc
        if canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n" != raw:
            raise MonitoringWorkspaceError(
                f"monitoring artifact {path.name} is not in canonical form"
            )
        return model

    # -- public API ---------------------------------------------------------

    def commit_run(
        self,
        run: MonitoringRunV1,
        *,
        watchlist: WatchlistSpecV1,
        batch: MonitoringEventBatchV1,
    ) -> MonitoringStatePointerV1:
        """Durably persist a run and move the pointer to its next state.

        Order is fixed: watchlist snapshot, event batch, run, next state,
        pointer.  The pointer moves only after every artifact is durably
        written; any earlier failure leaves the previous committed state
        readable and the pointer untouched.
        """

        if run.watchlist_id != watchlist.watchlist_id:
            raise MonitoringWorkspaceError("run and watchlist identities differ")
        if run.event_batch_id != batch.batch_id:
            raise MonitoringWorkspaceError("run and event batch identities differ")
        if run.next_state.watchlist_id != watchlist.watchlist_id:
            raise MonitoringWorkspaceError("run next_state belongs to another watchlist")

        self._commit_bytes(
            self.watchlist_path(watchlist),
            _artifact_bytes(watchlist),
            "artifact",
        )
        self._commit_bytes(
            self.event_batch_path(batch.batch_id),
            _artifact_bytes(batch),
            "artifact",
        )
        self._commit_bytes(self.run_path(run.run_id), _artifact_bytes(run), "artifact")
        self._commit_bytes(
            self.state_path(run.next_state.state_id),
            _artifact_bytes(run.next_state),
            "artifact",
        )
        pointer = MonitoringStatePointerV1.build(
            watchlist_id=watchlist.watchlist_id,
            state_id=run.next_state.state_id,
            run_id=run.next_state.last_committed_run_id or run.run_id,
        )
        self._commit_bytes(
            self.pointer_path(watchlist.watchlist_id),
            _artifact_bytes(pointer),
            "pointer",
        )
        return pointer

    def load_current_state(self, watchlist_id: str) -> WatchlistStateV1 | None:
        """Return the committed state for a watchlist, or None before any run."""

        pointer_file = self.pointer_path(watchlist_id)
        if not pointer_file.exists():
            return None
        pointer = self._read_model(pointer_file, MonitoringStatePointerV1)
        if not isinstance(pointer, MonitoringStatePointerV1):
            raise MonitoringWorkspaceError("state pointer artifact has unexpected type")
        if pointer.watchlist_id != watchlist_id:
            raise MonitoringWorkspaceError(
                f"state pointer for {watchlist_id!r} references watchlist "
                f"{pointer.watchlist_id!r}"
            )
        state = self._read_model(self.state_path(pointer.state_id), WatchlistStateV1)
        if not isinstance(state, WatchlistStateV1):
            raise MonitoringWorkspaceError("state artifact has unexpected type")
        if state.state_id != pointer.state_id or state.watchlist_id != watchlist_id:
            raise MonitoringWorkspaceError(
                "committed state does not match the current-state pointer"
            )
        return state

    def load_run(self, run_id: str) -> MonitoringRunV1:
        run = self._read_model(self.run_path(run_id), MonitoringRunV1)
        if not isinstance(run, MonitoringRunV1):
            raise MonitoringWorkspaceError("run artifact has unexpected type")
        return run

    def status(self, watchlist_id: str) -> MonitoringStatusV1:
        """Project the committed state into the offline status contract."""

        state = self.load_current_state(watchlist_id)
        if state is None:
            return MonitoringStatusV1.model_validate(
                {
                    "watchlist_id": watchlist_id,
                    "availability": "NOT_AVAILABLE",
                }
            )
        entries = [
            MonitoringStatusEntryV1.model_validate(
                {
                    "listing_id": entry.listing_id,
                    "last_analysis_id": entry.last_analysis_id,
                    "last_surface_id": entry.last_surface_id,
                    "last_analysis_as_of": entry.last_analysis_as_of,
                    "last_profile_id": entry.last_profile_id,
                    "last_deterministic_result": entry.last_deterministic_result,
                    "last_filing_id": entry.last_filing_id,
                    "cursors": [
                        cursor.model_dump(mode="json") for cursor in entry.cursors
                    ],
                    "processed_event_count": len(entry.processed_events),
                    "open_questions": entry.open_questions,
                }
            )
            for entry in state.entries
        ]
        return MonitoringStatusV1.model_validate(
            {
                "watchlist_id": watchlist_id,
                "availability": "AVAILABLE",
                "state_id": state.state_id,
                "last_committed_run_id": state.last_committed_run_id,
                "entries": [entry.model_dump(mode="json") for entry in entries],
            }
        )


def _artifact_bytes(model) -> bytes:
    return canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "FailureInjector",
    "MonitoringWorkspace",
    "MonitoringWorkspaceError",
    "WriteKind",
]
