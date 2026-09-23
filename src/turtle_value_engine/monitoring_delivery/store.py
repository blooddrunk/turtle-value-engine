"""Immutable, atomic local storage for Phase 6-D2B delivery artifacts.

The delivery ledger is deliberately separate from the Phase 6-D1 cycle store
and the Phase 6-D2A runner store: a delivery failure must never contaminate
monitoring/runner state, and delivery retry state must never be mixed into
either.  Intents and attempts are immutable create-only artifacts; the latest
state is an atomically replaced pointer that moves last.  A crash can
therefore leave an intent without attempts (an undelivered delivery to run)
or an attempt without a published state (a deterministically repairable
pointer), but never a durable false ``DELIVERED`` state.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from turtle_value_engine.monitoring.canonical import canonical_json_bytes

from .contracts import (
    MonitoringDeliveryAttemptV1,
    MonitoringDeliveryIntentV1,
    MonitoringDeliveryStateV1,
    MonitoringDispatchClaimV1,
)

DeliveryWriteKind = Literal["artifact", "pointer"]
FailureInjector = Callable[[Path, DeliveryWriteKind], None]
ModelT = TypeVar("ModelT", bound=BaseModel)


class DeliveryLedgerError(ValueError):
    """Raised when a delivery artifact is missing, corrupt or conflicting."""


class DeliveryLedgerStore:
    """Filesystem ledger for delivery intents, attempts and latest state."""

    def __init__(
        self,
        root: str | Path,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self.root = Path(root)
        self._failure_injector = failure_injector

    def intent_path(self, delivery_id: str) -> Path:
        return self.root / "intents" / f"{delivery_id}.json"

    def attempts_dir(self, delivery_id: str) -> Path:
        return self.root / "attempts" / delivery_id

    def attempt_path(self, delivery_id: str, attempt_number: int) -> Path:
        return self.attempts_dir(delivery_id) / f"{attempt_number:06d}.json"

    def state_path(self, delivery_id: str) -> Path:
        return self.root / "state" / f"{delivery_id}.json"

    def claims_dir(self, delivery_id: str) -> Path:
        return self.root / "claims" / delivery_id

    def claim_path(self, delivery_id: str, attempt_number: int) -> Path:
        return self.claims_dir(delivery_id) / f"{attempt_number:06d}.json"

    def lock_path(self, delivery_id: str) -> Path:
        """Path of the per-delivery OS single-flight lock slot (6-D2B-R1)."""

        return self.root / "locks" / f"{delivery_id}.lock"

    def _inject_failure(self, path: Path, kind: DeliveryWriteKind) -> None:
        if self._failure_injector is not None:
            self._failure_injector(path, kind)

    def _commit_bytes(self, path: Path, content: bytes, kind: DeliveryWriteKind) -> None:
        try:
            self._inject_failure(path, kind)
        except Exception as exc:
            raise DeliveryLedgerError(
                f"delivery ledger write failed at {path}: {type(exc).__name__}"
            ) from exc
        if kind == "artifact":
            self._write_immutable(path, content)
        else:
            self._write_pointer(path, content)

    def _write_immutable(self, path: Path, content: bytes) -> None:
        if path.is_symlink() or path.exists():
            if path.is_symlink() or not path.is_file():
                raise DeliveryLedgerError(f"delivery artifact is not a regular file: {path}")
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise DeliveryLedgerError(
                    f"cannot read existing delivery artifact: {exc}"
                ) from exc
            if existing != content:
                raise DeliveryLedgerError(
                    f"delivery artifact {path.name} already has conflicting content"
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
            os.link(temporary_path, path)
            _fsync_directory(path.parent)
            temporary_path.unlink()
            temporary_path = None
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise DeliveryLedgerError(
                    f"cannot read existing delivery artifact: {exc}"
                ) from exc
            if existing != content:
                raise DeliveryLedgerError(
                    f"delivery artifact {path.name} already has conflicting content"
                )
        except OSError as exc:
            raise DeliveryLedgerError(f"cannot persist delivery artifact: {exc}") from exc
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
            raise DeliveryLedgerError(f"cannot update delivery state {path}: {exc}") from exc
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

    @staticmethod
    def _verify_regular_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise DeliveryLedgerError(f"delivery artifact is missing or not a file: {path}")

    def _read_model(self, path: Path, model_type: type[ModelT]) -> ModelT:
        self._verify_regular_file(path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_number)
            model = model_type.model_validate(payload)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise DeliveryLedgerError(f"corrupt delivery artifact {path}: {exc}") from exc
        if canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n" != raw:
            raise DeliveryLedgerError(f"delivery artifact {path.name} is not canonical")
        return model

    def save_intent(self, intent: MonitoringDeliveryIntentV1) -> None:
        self._commit_bytes(
            self.intent_path(intent.delivery_id), intent.canonical_bytes() + b"\n", "artifact"
        )

    def load_intent(self, delivery_id: str) -> MonitoringDeliveryIntentV1:
        intent = self._read_model(self.intent_path(delivery_id), MonitoringDeliveryIntentV1)
        if intent.delivery_id != delivery_id:
            raise DeliveryLedgerError("delivery intent does not match its ledger slot")
        return intent

    def intent_exists(self, delivery_id: str) -> bool:
        path = self.intent_path(delivery_id)
        if path.is_symlink():
            raise DeliveryLedgerError(f"delivery intent is not a regular file: {path}")
        return path.exists()

    def save_attempt(self, attempt: MonitoringDeliveryAttemptV1) -> None:
        self._commit_bytes(
            self.attempt_path(attempt.delivery_id, attempt.attempt_number),
            attempt.canonical_bytes() + b"\n",
            "artifact",
        )

    def load_attempt(
        self, delivery_id: str, attempt_number: int
    ) -> MonitoringDeliveryAttemptV1:
        attempt = self._read_model(
            self.attempt_path(delivery_id, attempt_number), MonitoringDeliveryAttemptV1
        )
        if attempt.delivery_id != delivery_id or attempt.attempt_number != attempt_number:
            raise DeliveryLedgerError("delivery attempt does not match its ledger slot")
        return attempt

    def list_attempts(self, delivery_id: str) -> list[MonitoringDeliveryAttemptV1]:
        """Return the validated attempt set in monotonic order, fail-closed.

        Attempt numbers are dispatch-slot numbers, and a slot whose outcome
        never persisted (an unresolved orphan consumed by a later retry)
        leaves a legitimate gap, so contiguity is not required here — every
        attempt must still be unique and sorted, and the service validates
        that each attempt has its durable claim slot.
        """

        return self._list_numbered(
            self.attempts_dir(delivery_id),
            lambda path: self.load_attempt(delivery_id, int(path.stem)),
            contiguous=False,
        )

    # -- dispatch claims (6-D2B-R1) -------------------------------------

    def save_claim(self, claim: MonitoringDispatchClaimV1) -> None:
        """Persist durable dispatch-start evidence (immutable create-only)."""

        self._commit_bytes(
            self.claim_path(claim.delivery_id, claim.attempt_number),
            claim.canonical_bytes() + b"\n",
            "artifact",
        )

    def load_claim(
        self, delivery_id: str, attempt_number: int
    ) -> MonitoringDispatchClaimV1:
        claim = self._read_model(
            self.claim_path(delivery_id, attempt_number), MonitoringDispatchClaimV1
        )
        if claim.delivery_id != delivery_id or claim.attempt_number != attempt_number:
            raise DeliveryLedgerError("delivery dispatch claim does not match its slot")
        return claim

    def list_claims(self, delivery_id: str) -> list[MonitoringDispatchClaimV1]:
        """Return the validated dispatch-claim set in monotonic order, fail-closed.

        The claim set is the retry-budget ledger: slots are allocated
        monotonically ``1..N`` with no skip (6-D2B-R2), so a gap or duplicate
        is contradictory evidence and fails closed.
        """

        return self._list_numbered(
            self.claims_dir(delivery_id),
            lambda path: self.load_claim(delivery_id, int(path.stem)),
            contiguous=True,
        )

    def _list_numbered(
        self, directory: Path, loader, *, contiguous: bool
    ) -> list:
        if not directory.exists():
            return []
        records: list = []
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise DeliveryLedgerError(f"delivery artifact is not a regular file: {path}")
            if path.suffix != ".json" or path.name.startswith("."):
                continue
            records.append(loader(path))
        numbers = [int(record.attempt_number) for record in records]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            raise DeliveryLedgerError(
                f"delivery records in {directory.name} must be unique and sorted"
            )
        if contiguous and numbers != list(range(1, len(numbers) + 1)):
            raise DeliveryLedgerError(
                f"delivery records in {directory.name} must be contiguous from one"
            )
        return records

    def publish_state(self, state: MonitoringDeliveryStateV1) -> None:
        self._commit_bytes(
            self.state_path(state.delivery_id), state.canonical_bytes() + b"\n", "pointer"
        )

    def load_state(self, delivery_id: str) -> MonitoringDeliveryStateV1 | None:
        path = self.state_path(delivery_id)
        if not path.exists():
            return None
        state = self._read_model(path, MonitoringDeliveryStateV1)
        if state.delivery_id != delivery_id:
            raise DeliveryLedgerError("delivery state does not match its ledger slot")
        return state

    def list_delivery_ids(self) -> list[str]:
        """List delivery identities present in the ledger (intent slots)."""

        directory = self.root / "intents"
        if not directory.exists():
            return []
        ids: list[str] = []
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix == ".json" and not path.name.startswith("."):
                ids.append(path.stem)
        return ids


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DeliveryLedgerError",
    "DeliveryLedgerStore",
    "DeliveryWriteKind",
    "FailureInjector",
]
