"""Per-delivery OS-level single-flight exclusion for Phase 6-D2B-R1.

The flock is the first and only liveness authority for one ``delivery_id``:
it is taken non-blocking **before** any ledger state inspection, dispatch
claim, transport call, attempt persistence or latest-state publication, and
it is held across all of them.  The kernel releases it when the holding
process exits for any reason, so a crashed invocation cannot block the next
one, while a live invocation makes every other local process fail fast with
zero outbound requests.

Classification follows the Phase 6-D2A-R1 truthfulness discipline:

- only the platform's real lock contention (``BlockingIOError`` /
  ``EAGAIN`` / ``EWOULDBLOCK`` / ``EACCES``) maps to
  ``DeliveryLockBusyError``;
- every other open/lock/filesystem failure fails closed as
  ``DeliveryLockError`` and must never pose as a busy classification.

The lock file carries no mutable holder record: the slot name is the
delivery identity itself, so no JSON authority can preempt the kernel lock.
The receiver's ``Idempotency-Key`` is never relied on to resolve local
concurrency.
"""

from __future__ import annotations

import errno
import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOCK_CONTENTION_ERRNOS = frozenset(
    code
    for code in (
        getattr(errno, "EAGAIN", None),
        getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EACCES", None),
    )
    if code is not None
)


class DeliveryLockError(ValueError):
    """A non-contention lock/filesystem failure; the delivery fails closed."""


class DeliveryLockBusyError(DeliveryLockError):
    """Another live invocation holds this delivery; this invocation does nothing."""

    def __init__(self, delivery_id: str) -> None:
        super().__init__(
            "DELIVERY_BUSY: another live invocation is delivering this delivery identity"
        )
        self.delivery_id = delivery_id


def _is_lock_contention(exc: OSError) -> bool:
    """True only for the platform's real non-blocking lock-contention errors."""

    return isinstance(exc, BlockingIOError) or exc.errno in _LOCK_CONTENTION_ERRNOS


@contextmanager
def delivery_single_flight(lock_path: str | Path, delivery_id: str) -> Iterator[None]:
    """Hold the exclusive per-delivery lock or fail fast with a typed error."""

    path = Path(lock_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise DeliveryLockError(f"cannot open delivery lock slot {path}: {exc}") from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if _is_lock_contention(exc):
                raise DeliveryLockBusyError(delivery_id) from exc
            raise DeliveryLockError(f"cannot lock delivery slot {path}: {exc}") from exc
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = [
    "DeliveryLockBusyError",
    "DeliveryLockError",
    "delivery_single_flight",
]
