"""Immutable, atomic local storage for Phase 6-D2A runner artifacts."""

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
    RunnerActivationIntentV1,
    RunnerActivePointerV1,
    RunnerLatestPointerV1,
    RunnerReceiptV1,
)

RunnerWriteKind = Literal["artifact", "pointer", "clear"]
FailureInjector = Callable[[Path, RunnerWriteKind], None]
ModelT = TypeVar("ModelT", bound=BaseModel)


class RunnerStoreError(ValueError):
    """Raised when a D2A runner artifact is missing, corrupt or conflicting."""


class RunnerStore:
    """Filesystem store for runner activations, receipts and pointers.

    Activation intents and receipts are immutable create-only artifacts; the
    active/latest pointers are atomically replaced files that move last.  A
    crash can therefore leave an intent without a receipt (an unfinished
    activation to resume) or a receipt without a pointer (a repairable
    pointer), but never a durable false terminal state.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self.root = Path(root)
        self._failure_injector = failure_injector

    def intent_path(self, activation_id: str) -> Path:
        return self.root / "activations" / f"{activation_id}.json"

    def receipt_path(self, activation_id: str) -> Path:
        return self.root / "receipts" / f"{activation_id}.json"

    def latest_path(self, runner_id: str) -> Path:
        return self.root / "latest" / f"{runner_id}.json"

    def active_path(self, runner_id: str) -> Path:
        return self.root / "active" / f"{runner_id}.json"

    def lease_path(self, runner_id: str) -> Path:
        return self.root / "leases" / f"{runner_id}.json"

    def _inject_failure(self, path: Path, kind: RunnerWriteKind) -> None:
        if self._failure_injector is not None:
            self._failure_injector(path, kind)

    def _commit_bytes(self, path: Path, content: bytes, kind: RunnerWriteKind) -> None:
        try:
            self._inject_failure(path, kind)
        except Exception as exc:
            raise RunnerStoreError(
                f"runner store write failed at {path}: {type(exc).__name__}"
            ) from exc
        if kind == "artifact":
            self._write_immutable(path, content)
        else:
            self._write_pointer(path, content)

    def _write_immutable(self, path: Path, content: bytes) -> None:
        if path.is_symlink() or path.exists():
            if path.is_symlink() or not path.is_file():
                raise RunnerStoreError(f"runner artifact is not a regular file: {path}")
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise RunnerStoreError(f"cannot read existing runner artifact: {exc}") from exc
            if existing != content:
                raise RunnerStoreError(
                    f"runner artifact {path.name} already has conflicting content"
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
                raise RunnerStoreError(f"cannot read existing runner artifact: {exc}") from exc
            if existing != content:
                raise RunnerStoreError(
                    f"runner artifact {path.name} already has conflicting content"
                )
        except OSError as exc:
            raise RunnerStoreError(f"cannot persist runner artifact {path}: {exc}") from exc
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
            raise RunnerStoreError(f"cannot update runner pointer {path}: {exc}") from exc
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
            raise RunnerStoreError(f"runner artifact is missing or not a file: {path}")

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
            raise RunnerStoreError(f"corrupt runner artifact {path}: {exc}") from exc
        if canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n" != raw:
            raise RunnerStoreError(f"runner artifact {path.name} is not canonical")
        return model

    def save_intent(self, intent: RunnerActivationIntentV1) -> None:
        self._commit_bytes(
            self.intent_path(intent.activation_id), intent.canonical_bytes() + b"\n", "artifact"
        )

    def load_intent(self, activation_id: str) -> RunnerActivationIntentV1:
        return self._read_model(self.intent_path(activation_id), RunnerActivationIntentV1)

    def receipt_exists(self, activation_id: str) -> bool:
        path = self.receipt_path(activation_id)
        if path.is_symlink():
            raise RunnerStoreError(f"runner receipt is not a regular file: {path}")
        return path.exists()

    def load_receipt(self, activation_id: str) -> RunnerReceiptV1 | None:
        path = self.receipt_path(activation_id)
        if not path.exists():
            return None
        return self._read_model(path, RunnerReceiptV1)

    def publish_receipt(self, receipt: RunnerReceiptV1) -> RunnerLatestPointerV1:
        """Persist the immutable receipt, then atomically publish it."""

        self._commit_bytes(
            self.receipt_path(receipt.activation_id), receipt.canonical_bytes() + b"\n", "artifact"
        )
        pointer = RunnerLatestPointerV1.build(
            runner_id=receipt.runner_id,
            activation_id=receipt.activation_id,
            cycle_id=receipt.cycle_id,
            receipt_content_sha256=receipt.content_sha256,
        )
        self._commit_bytes(
            self.latest_path(receipt.runner_id), pointer.canonical_bytes() + b"\n", "pointer"
        )
        return pointer

    def load_latest(self, runner_id: str) -> RunnerLatestPointerV1 | None:
        path = self.latest_path(runner_id)
        if not path.exists():
            return None
        pointer = self._read_model(path, RunnerLatestPointerV1)
        if pointer.runner_id != runner_id:
            raise RunnerStoreError("runner latest pointer does not match its runner slot")
        return pointer

    def set_active(self, intent: RunnerActivationIntentV1) -> RunnerActivePointerV1:
        pointer = RunnerActivePointerV1.build(
            runner_id=intent.runner_id,
            activation_id=intent.activation_id,
            intent_content_sha256=intent.content_sha256,
        )
        self._commit_bytes(
            self.active_path(intent.runner_id), pointer.canonical_bytes() + b"\n", "pointer"
        )
        return pointer

    def load_active(self, runner_id: str) -> RunnerActivePointerV1 | None:
        path = self.active_path(runner_id)
        if not path.exists():
            return None
        pointer = self._read_model(path, RunnerActivePointerV1)
        if pointer.runner_id != runner_id:
            raise RunnerStoreError("runner active pointer does not match its runner slot")
        return pointer

    def clear_active(self, runner_id: str) -> None:
        path = self.active_path(runner_id)
        try:
            self._inject_failure(path, "clear")
        except Exception as exc:
            raise RunnerStoreError(
                f"runner store clear failed at {path}: {type(exc).__name__}"
            ) from exc
        if not path.exists():
            return
        try:
            if path.is_symlink() or not path.is_file():
                raise RunnerStoreError(f"runner active pointer is not a regular file: {path}")
            path.unlink()
            _fsync_directory(path.parent)
        except OSError as exc:
            raise RunnerStoreError(f"cannot clear runner active pointer {path}: {exc}") from exc

    def list_unfinished_activations(self, runner_id: str) -> list[RunnerActivationIntentV1]:
        """Return validated receipt-less intents for one runner identity.

        Any corrupt activation or receipt artifact in the store fails closed,
        because a receipt that cannot be validated must not be mistaken for a
        completed activation.
        """

        activations_dir = self.root / "activations"
        receipts_dir = self.root / "receipts"
        if not activations_dir.exists():
            return []
        unfinished: list[RunnerActivationIntentV1] = []
        for path in sorted(activations_dir.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise RunnerStoreError(f"runner artifact is not a regular file: {path}")
            if path.suffix != ".json" or path.name.startswith("."):
                continue
            receipt_candidate = receipts_dir / path.name
            if receipt_candidate.is_symlink():
                raise RunnerStoreError(
                    f"runner receipt is not a regular file: {receipt_candidate}"
                )
            if receipt_candidate.exists():
                self._read_model(receipt_candidate, RunnerReceiptV1)
                continue
            intent = self._read_model(path, RunnerActivationIntentV1)
            if intent.runner_id == runner_id:
                unfinished.append(intent)
        return unfinished

    def list_runner_ids(self) -> list[str]:
        """List runner identities present in pointer or lease slots."""

        ids: set[str] = set()
        for slot in ("latest", "active", "leases"):
            directory = self.root / slot
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if path.is_file() and path.suffix == ".json" and not path.name.startswith("."):
                    ids.add(path.stem)
        return sorted(ids)


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "FailureInjector",
    "RunnerStore",
    "RunnerStoreError",
    "RunnerWriteKind",
]
