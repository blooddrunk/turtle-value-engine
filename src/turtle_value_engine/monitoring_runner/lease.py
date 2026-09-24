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
  authority on the work path; persisted lease JSON is inspected only after
  this process owns the OS lock;
- only the platform's real contention errors (``BlockingIOError`` or
  ``EAGAIN``/``EWOULDBLOCK``/``EACCES``) map to ``RunnerLeaseBusyError``;
  every other open/lock failure fails closed as ``RunnerLeaseError``;
- a canonical prior record whose ``runner_id`` differs from this lease slot
  is a persisted-state conflict and fails closed instead of being
  overwritten;
- holder-record writes prove full-byte persistence through a complete
  write loop before the fsync is allowed to claim success.

Observation rules (Phase 6-D3-R1):

- ``RunnerLease.probe()`` is strictly non-interfering: it never acquires any
  OS lock on the lease slot, so a status/D3 read can never make an otherwise
  uncontended ``held()`` invocation classify the slot as busy;
- liveness is instead proven passively from the kernel's ``/proc/locks``
  table: a ``FLOCK`` entry bound to the lease file's device/inode proves a
  live exclusive holder without taking one;
- when the passive capability is unavailable (non-Linux platform, unreadable
  or untrustworthy lock table, persistently changing bytes), the probe
  returns the explicit conservative ``UNKNOWN`` state instead of
  fabricating ``LIVE``/``FREE``/``ABANDONED``;
- ``corrupt`` remains a *proven* statement only: it is ``True`` exclusively
  when stable bytes with a proven lock-free slot still fail canonical
  validation.
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
from enum import StrEnum
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

# Bound the ``/proc/locks`` read so an unbounded kernel lock table cannot
# turn a status read into unbounded memory growth; a truncated table cannot
# prove liveness and is classified as capability-unavailable instead.
_LOCK_TABLE_READ_LIMIT = 8 * 1024 * 1024

# Byte-driven re-observation bound.  This is not a timing workaround: each
# extra attempt happens only because the lease bytes demonstrably changed
# under the observer (writes happen exclusively under the authoritative
# exclusive lock), and exhaustion degrades to the conservative UNKNOWN.
_PROBE_MAX_ATTEMPTS = 3


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


def _read_raw_bytes(descriptor: int) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        return _read_all(descriptor)
    except OSError as exc:
        raise RunnerLeaseError(f"cannot read runner lease record: {exc}") from exc


def _decode_record_bytes(raw: bytes) -> RunnerLeaseV1:
    """Decode canonical lease bytes, raising typed errors for bad content."""

    if not raw.strip():
        raise RunnerLeaseError("runner lease record is empty")
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


def _parse_record_bytes(raw: bytes) -> RunnerLeaseV1 | None:
    """Decode canonical lease bytes, or ``None`` for any invalid content."""

    if not raw.strip():
        return None
    try:
        return _decode_record_bytes(raw)
    except RunnerLeaseError:
        return None


def _read_record_from_fd(descriptor: int) -> RunnerLeaseV1 | None:
    raw = _read_raw_bytes(descriptor)
    if not raw.strip():
        return None
    return _decode_record_bytes(raw)


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


class _LockScan(StrEnum):
    """Passive result of looking for a live exclusive holder in the kernel."""

    HOLDER_VISIBLE = "HOLDER_VISIBLE"
    NO_HOLDER = "NO_HOLDER"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"


def _scan_flock_holder(
    device: int, inode: int, *, table_path: str = "/proc/locks"
) -> _LockScan:
    """Look for a live ``flock`` holder on one file, purely by observation.

    Reads the kernel's ``/proc/locks`` table and reports whether any granted
    ``FLOCK`` entry is bound to ``device``:``inode``.  Taking no lock is the
    entire point: this must never contend with ``RunnerLease.held()``.

    Any condition that would make the table untrustworthy (missing file,
    read failure, truncation, unparseable content) reports
    ``CAPABILITY_UNAVAILABLE`` so callers degrade to the conservative typed
    ``UNKNOWN`` state instead of fabricating ``LIVE`` or ``FREE``.
    """

    try:
        with open(table_path, "rb") as table:
            raw = table.read(_LOCK_TABLE_READ_LIMIT + 1)
    except OSError:
        return _LockScan.CAPABILITY_UNAVAILABLE
    if len(raw) > _LOCK_TABLE_READ_LIMIT:
        return _LockScan.CAPABILITY_UNAVAILABLE
    needle = f"{os.major(device):02x}:{os.minor(device):02x}:{inode}"
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError:
        return _LockScan.CAPABILITY_UNAVAILABLE
    # Line layout: ``id: CLASS TYPE ACCESS PID DEV:INO START END``.  Only
    # ``FLOCK`` entries can represent the authoritative runner lease;
    # ``POSIX``/``OFDLCK``/``LEASE`` entries on the same inode are different
    # lock domains and are skipped, while ``->`` lines are blocked
    # *requests*, not granted locks.
    known_classes = frozenset({"FLOCK", "POSIX", "OFDLCK", "LEASE"})
    for line in lines:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "->":
            continue
        if len(fields) < 8 or fields[1] not in known_classes:
            # A line the parser does not recognize cannot be trusted to
            # prove the absence of a holder.
            return _LockScan.CAPABILITY_UNAVAILABLE
        if fields[1] == "FLOCK" and fields[5] == needle:
            return _LockScan.HOLDER_VISIBLE
    return _LockScan.NO_HOLDER


def _observation_result(
    state: LeaseState, raw: bytes | None, *, corrupt: bool
) -> dict[str, object]:
    record = None if raw is None else _parse_record_bytes(raw)
    return {
        "state": state.value,
        "record": None if record is None else _public_record(record),
        "corrupt": corrupt,
    }


def _probe_no_holder_stable(raw: bytes) -> dict[str, object]:
    # The slot is proven lock-free and the bytes were stable across both
    # reads, so the classification below is a proven statement.
    record = _parse_record_bytes(raw)
    if record is None and raw.strip():
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
        """Classify lease liveness without acquiring any OS lock (6-D3-R1).

        This path is purely observational and can never contend with
        ``held()``: it opens the slot read-only, never flocks it, and derives
        liveness from the kernel's ``/proc/locks`` table instead.  A visible
        ``FLOCK`` entry proves ``LIVE``; a trustworthy lock-free table plus
        byte-stable reads proves ``ABANDONED`` (or ``FREE`` before the slot
        file exists).  When liveness cannot be proven passively, the explicit
        conservative ``UNKNOWN`` state is returned — never a fabricated
        classification.  ``corrupt`` is ``True`` only for a *proven*
        lock-free slot whose stable bytes still fail canonical validation.
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
            second = b""
            for _ in range(_PROBE_MAX_ATTEMPTS):
                stat = os.fstat(descriptor)
                first = _read_raw_bytes(descriptor)
                scan_before = _scan_flock_holder(stat.st_dev, stat.st_ino)
                second = _read_raw_bytes(descriptor)
                scan_after = _scan_flock_holder(stat.st_dev, stat.st_ino)
                if (
                    scan_before is _LockScan.HOLDER_VISIBLE
                    or scan_after is _LockScan.HOLDER_VISIBLE
                ):
                    # A live exclusive holder is proven by the kernel lock
                    # table itself; its record may still be mid-write, so an
                    # unparseable snapshot degrades to no record.
                    return _observation_result(LeaseState.LIVE, second, corrupt=False)
                if (
                    scan_before is _LockScan.CAPABILITY_UNAVAILABLE
                    or scan_after is _LockScan.CAPABILITY_UNAVAILABLE
                ):
                    # Passive liveness cannot be established on this
                    # platform/state; never fabricate, never fail the read.
                    return _observation_result(LeaseState.UNKNOWN, second, corrupt=False)
                if first != second:
                    # Lease bytes only ever change under the authoritative
                    # exclusive lock, so a difference proves a writer was
                    # active inside this observation window.  Re-observe;
                    # a finished writer leaves stable bytes behind.
                    continue
                return _probe_no_holder_stable(second)
            # Bytes kept changing across every attempt: a live writer was
            # demonstrably active throughout, but current liveness cannot be
            # pinned to a single instant.  Report the conservative state.
            return _observation_result(LeaseState.UNKNOWN, second, corrupt=False)
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
