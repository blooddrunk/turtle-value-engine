"""Single-host exclusive lease for one unattended runner identity.

Liveness is proven by an OS-level ``flock`` held on the lease file for the
whole invocation.  The kernel releases that lock when the holding process
exits for any reason, so a crashed or killed runner leaves an abandoned
record that the next invocation may recover explicitly.  A live holder can
never be stolen from: while the lock is held, every other invocation fails
fast with a typed busy classification and performs no provider, model or D1
work at all.

Classification rules (Phase 6-D2A-R1):

- the non-blocking ``flock`` is tried first and is the only liveness
  authority; persisted lease JSON is inspected only after this process owns
  the OS lock;
- only the platform's real contention errors (``BlockingIOError`` or
  ``EAGAIN``/``EWOULDBLOCK``/``EACCES``) map to ``RunnerLeaseBusyError``;
  every other open/lock failure fails closed as ``RunnerLeaseError``;
- a canonical prior record whose ``runner_id`` differs from this lease slot
  is a persisted-state conflict and fails closed instead of being
  overwritten;
- holder-record writes prove full-byte persistence through a complete
  write loop before the fsync is allowed to claim success.
"""

from __future__ import annotations

import errno
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

_LOCK_CONTENTION_ERRNOS = frozenset(
    code
    for code in (
        getattr(errno, "EAGAIN", None),
        getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EACCES", None),
    )
    if code is not None
)


class RunnerLeaseError(ValueError):
    """Raised when the lease slot or its record must fail closed."""


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
            _write_all_bytes(self._descriptor, payload)
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


def _is_lock_contention(exc: OSError) -> bool:
    """True only for the platform's real non-blocking lock-contention errors.

    ``BlockingIOError`` (``EAGAIN``/``EWOULDBLOCK``) and an ``EACCES`` flock
    rejection prove that another live invocation owns the slot.  Any other
    errno (``ENOLCK``, bad descriptor, filesystem failure, ...) is an
    unrelated OS failure and must not pose as a liveness classification.
    """

    return isinstance(exc, BlockingIOError) or exc.errno in _LOCK_CONTENTION_ERRNOS


def _try_flock_exclusive(descriptor: int, path: Path) -> bool:
    """Take the non-blocking exclusive lock, classifying failures truthfully.

    Returns ``True`` when this process owns the lock.  Real contention
    returns ``False``; every other lock failure raises ``RunnerLeaseError``.
    """

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if _is_lock_contention(exc):
            return False
        raise RunnerLeaseError(f"cannot lock runner lease slot {path}: {exc}") from exc
    return True


def _write_all_bytes(descriptor: int, payload: bytes) -> None:
    """Write the complete payload or fail; a short write is never success."""

    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError(f"os.write made no progress with {len(remaining)} bytes left")
        remaining = remaining[written:]


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
        """Acquire the lease exclusively or fail fast with a typed error.

        The kernel lock is the liveness authority and is tried first; the
        persisted record is read only after this process owns the lock, so a
        torn or corrupt record can never preempt a real busy classification.
        """

        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise RunnerLeaseError(f"cannot open runner lease slot {path}: {exc}") from exc
        try:
            if not _try_flock_exclusive(descriptor, path):
                # A live holder owns the slot; report its record without
                # touching any provider, model or D1 boundary.
                raise RunnerLeaseBusyError(_safe_read_record(descriptor))
            prior = _read_record_from_fd(descriptor)
            if prior is not None and prior.runner_id != self.runner_id:
                raise RunnerLeaseError(
                    f"runner lease slot {path} holds a canonical record bound to "
                    f"runner {prior.runner_id!r}, not this slot's runner "
                    f"{self.runner_id!r}; refusing to overwrite foreign runner state"
                )
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
        """Classify lease liveness without taking the slot for work.

        The same truthfulness rules as the run path apply: an existing slot
        that cannot be opened is never reported as ``FREE``, and a lock
        failure other than real contention is never reported as ``LIVE``.
        """

        path = self.path
        if not path.exists():
            return {"state": LeaseState.FREE.value, "record": None, "corrupt": False}
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except FileNotFoundError:
            return {"state": LeaseState.FREE.value, "record": None, "corrupt": False}
        except OSError as exc:
            raise RunnerLeaseError(f"cannot open runner lease slot {path}: {exc}") from exc
        try:
            if not _try_flock_exclusive(descriptor, path):
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
