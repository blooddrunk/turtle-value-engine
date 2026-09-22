"""Single-host exclusive lease for one unattended runner identity.

Liveness is proven by an OS-level ``flock`` held on the lease file for the
whole invocation.  The kernel releases that lock when the holding process
exits for any reason, so a crashed or killed runner leaves an abandoned
record that the next invocation may recover explicitly.  A live holder can
never be stolen from: while the lock is held, every other invocation fails
fast with a typed busy classification and performs no provider, model or D1
work at all.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from turtle_value_engine.monitoring.canonical import canonical_json_bytes

from .contracts import LeaseState, RunnerLeaseV1
from .store import RunnerStore, RunnerStoreError

DefaultClock = Callable[[], datetime]


class RunnerLeaseError(ValueError):
    """Raised when the lease slot is busy or its record is corrupt."""


class RunnerLeaseBusyError(RunnerLeaseError):
    """Another live invocation holds the lease; this invocation does nothing."""

    def __init__(self, record: RunnerLeaseV1 | None) -> None:
        super().__init__("RUNNER_LEASE_BUSY: another live invocation holds the lease")
        self.record = record


@dataclass(frozen=True, slots=True)
class LeaseHandle:
    """Exclusive holder view of one runner lease slot."""

    runner_id: str
    acquired_stale_record: bool
    prior_record: RunnerLeaseV1 | None
    _descriptor: int
    _path: Path
    _ttl_seconds: int
    _clock: DefaultClock

    def record(self, activation_id: str | None) -> RunnerLeaseV1:
        """Write (or rewrite) the durable holder record under the held lock."""

        lease = RunnerLeaseV1.build(
            runner_id=self.runner_id,
            holder_token=uuid.uuid4().hex,
            activation_id=activation_id,
            acquired_at=self._clock(),
            lease_ttl_seconds=self._ttl_seconds,
        )
        payload = lease.canonical_bytes() + b"\n"
        try:
            os.lseek(self._descriptor, 0, os.SEEK_SET)
            os.ftruncate(self._descriptor, 0)
            os.write(self._descriptor, payload)
            os.fsync(self._descriptor)
        except OSError as exc:
            raise RunnerLeaseError(f"cannot persist runner lease record: {exc}") from exc
        return lease


def _read_record_from_fd(descriptor: int) -> RunnerLeaseV1 | None:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = _read_all(descriptor)
    except OSError as exc:
        raise RunnerLeaseError(f"cannot read runner lease record: {exc}") from exc
    if not raw.strip():
        return None
    try:
        model = RunnerLeaseV1.model_validate(json.loads(raw.decode("utf-8")))
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise RunnerLeaseError(f"corrupt runner lease record: {exc}") from exc
    if canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n" != raw:
        raise RunnerLeaseError("runner lease record is not canonical")
    return model


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


class RunnerLease:
    """Factory for exclusive, flock-backed runner leases on one host."""

    def __init__(
        self,
        root: str | Path,
        runner_id: str,
        *,
        ttl_seconds: int = 900,
        clock: DefaultClock | None = None,
    ) -> None:
        self.store = RunnerStore(root)
        self.runner_id = runner_id
        self.ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def path(self) -> Path:
        return self.store.lease_path(self.runner_id)

    @contextmanager
    def held(self) -> Iterator[LeaseHandle]:
        """Acquire the lease exclusively or fail fast with a typed error."""

        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise RunnerLeaseError(f"cannot open runner lease slot {path}: {exc}") from exc
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                # A live holder owns the slot; report its record without
                # touching any provider, model or D1 boundary.
                prior = _safe_read_record(descriptor)
                raise RunnerLeaseBusyError(prior) from None
            prior = _read_record_from_fd(descriptor)
            handle = LeaseHandle(
                runner_id=self.runner_id,
                acquired_stale_record=prior is not None,
                prior_record=prior,
                _descriptor=descriptor,
                _path=path,
                _ttl_seconds=self.ttl_seconds,
                _clock=self._clock,
            )
            yield handle
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def probe(self) -> dict[str, object]:
        """Classify lease liveness without taking the slot for work."""

        path = self.path
        if not path.exists():
            return {"state": LeaseState.FREE.value, "record": None, "corrupt": False}
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return {"state": LeaseState.FREE.value, "record": None, "corrupt": False}
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                record = _safe_read_record(descriptor)
                return {
                    "state": LeaseState.LIVE.value,
                    "record": None if record is None else _public_record(record),
                    "corrupt": False,
                }
            try:
                record = _read_record_from_fd(descriptor)
            except RunnerLeaseError:
                return {
                    "state": LeaseState.ABANDONED.value,
                    "record": None,
                    "corrupt": True,
                }
            return {
                "state": LeaseState.ABANDONED.value,
                "record": None if record is None else _public_record(record),
                "corrupt": False,
            }
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def validate_record(self) -> None:
        """Fail closed when the lease record exists but is corrupt.

        Called by the run path before any activation work so a torn or
        hand-edited lease record cannot be silently overwritten.
        """

        path = self.path
        if not path.exists():
            return
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError as exc:
            raise RunnerLeaseError(f"cannot open runner lease slot {path}: {exc}") from exc
        try:
            _read_record_from_fd(descriptor)
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _safe_read_record(descriptor: int) -> RunnerLeaseV1 | None:
    try:
        return _read_record_from_fd(descriptor)
    except RunnerLeaseError:
        return None


def _public_record(record: RunnerLeaseV1) -> dict[str, object]:
    # The holder token stays out of status output; it is not a credential,
    # but publishing it serves no operational purpose.
    return record.model_dump(
        mode="json", exclude={"holder_token", "content_sha256"}, warnings=False
    )


__all__ = [
    "DefaultClock",
    "LeaseHandle",
    "RunnerLease",
    "RunnerLeaseBusyError",
    "RunnerLeaseError",
    "RunnerStoreError",
]
