"""Immutable, atomic local storage for Phase 6-D1 cycle artifacts."""

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
    MonitoringAlertBatchV1,
    MonitoringCycleAcquisitionV1,
    MonitoringCyclePlanV1,
    MonitoringCyclePointerV1,
    MonitoringCycleResultV1,
    MonitoringCycleSpecV1,
)

CycleWriteKind = Literal["artifact", "pointer"]
FailureInjector = Callable[[Path, CycleWriteKind], None]
ModelT = TypeVar("ModelT", bound=BaseModel)


class MonitoringCycleStoreError(ValueError):
    """Raised when a D1 artifact is missing, corrupt or conflicting."""


class MonitoringCycleStore:
    """Filesystem store with terminal artifacts and an atomic latest pointer.

    Stage artifacts are deliberately immutable.  A crash may leave an
    acquisition or plan receipt behind, but it cannot create a durable false
    ``RUNNING`` cycle.  A result/outbox pair is published by writing the
    pointer last; if that final write fails, the next call can validate and
    repair the pointer without repeating acquisition or execution.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self.root = Path(root)
        self._failure_injector = failure_injector

    def spec_path(self, cycle_id: str) -> Path:
        return self.root / "specs" / f"{cycle_id}.json"

    def acquisition_path(self, cycle_id: str) -> Path:
        return self.root / "acquisitions" / f"{cycle_id}.json"

    def plan_path(self, cycle_id: str) -> Path:
        return self.root / "plans" / f"{cycle_id}.json"

    def alert_batch_path(self, alert_batch_id: str) -> Path:
        return self.root / "alerts" / f"{alert_batch_id}.json"

    def result_path(self, cycle_id: str) -> Path:
        return self.root / "cycles" / f"{cycle_id}.json"

    def pointer_path(self, cycle_id: str) -> Path:
        return self.root / "latest" / f"{cycle_id}.json"

    def _inject_failure(self, path: Path, kind: CycleWriteKind) -> None:
        if self._failure_injector is not None:
            self._failure_injector(path, kind)

    def _commit_bytes(self, path: Path, content: bytes, kind: CycleWriteKind) -> None:
        try:
            self._inject_failure(path, kind)
        except Exception as exc:
            raise MonitoringCycleStoreError(
                f"cycle store write failed at {path}: {type(exc).__name__}"
            ) from exc
        if kind == "pointer":
            self._write_pointer(path, content)
        else:
            self._write_immutable(path, content)

    def _write_immutable(self, path: Path, content: bytes) -> None:
        if path.is_symlink() or path.exists():
            if path.is_symlink() or not path.is_file():
                raise MonitoringCycleStoreError(f"cycle artifact is not a regular file: {path}")
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise MonitoringCycleStoreError(
                    f"cannot read existing cycle artifact: {exc}"
                ) from exc
            if existing != content:
                raise MonitoringCycleStoreError(
                    f"cycle artifact {path.name} already has conflicting content"
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
                raise MonitoringCycleStoreError(
                    f"cannot read existing cycle artifact: {exc}"
                ) from exc
            if existing != content:
                raise MonitoringCycleStoreError(
                    f"cycle artifact {path.name} already has conflicting content"
                )
        except OSError as exc:
            raise MonitoringCycleStoreError(f"cannot persist cycle artifact {path}: {exc}") from exc
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
            raise MonitoringCycleStoreError(
                f"cannot update cycle latest pointer {path}: {exc}"
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

    @staticmethod
    def _verify_regular_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise MonitoringCycleStoreError(f"cycle artifact is missing or not a file: {path}")

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
            raise MonitoringCycleStoreError(f"corrupt cycle artifact {path}: {exc}") from exc
        if canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n" != raw:
            raise MonitoringCycleStoreError(f"cycle artifact {path.name} is not canonical")
        return model

    def _save(self, path: Path, model: BaseModel) -> None:
        self._commit_bytes(
            path,
            canonical_json_bytes(model.model_dump(mode="json", warnings=False)) + b"\n",
            "artifact",
        )

    def save_spec(self, spec: MonitoringCycleSpecV1) -> None:
        self._save(self.spec_path(spec.cycle_id), spec)

    def save_acquisition(self, receipt: MonitoringCycleAcquisitionV1) -> None:
        self._save(self.acquisition_path(receipt.cycle_id), receipt)

    def save_plan(self, plan: MonitoringCyclePlanV1) -> None:
        self._save(self.plan_path(plan.cycle_id), plan)

    def save_alert_batch(self, batch: MonitoringAlertBatchV1) -> None:
        self._save(self.alert_batch_path(batch.alert_batch_id), batch)

    def save_result(self, result: MonitoringCycleResultV1) -> None:
        self._save(self.result_path(result.cycle_id), result)

    def load_spec(self, cycle_id: str) -> MonitoringCycleSpecV1:
        return self._read_model(self.spec_path(cycle_id), MonitoringCycleSpecV1)

    def load_acquisition(self, cycle_id: str) -> MonitoringCycleAcquisitionV1 | None:
        path = self.acquisition_path(cycle_id)
        return None if not path.exists() else self._read_model(path, MonitoringCycleAcquisitionV1)

    def load_plan(self, cycle_id: str) -> MonitoringCyclePlanV1 | None:
        path = self.plan_path(cycle_id)
        return None if not path.exists() else self._read_model(path, MonitoringCyclePlanV1)

    def load_alert_batch(self, alert_batch_id: str) -> MonitoringAlertBatchV1:
        return self._read_model(self.alert_batch_path(alert_batch_id), MonitoringAlertBatchV1)

    def load_result(self, cycle_id: str) -> MonitoringCycleResultV1:
        return self._read_model(self.result_path(cycle_id), MonitoringCycleResultV1)

    def load_pointer(self, cycle_id: str) -> MonitoringCyclePointerV1:
        return self._read_model(self.pointer_path(cycle_id), MonitoringCyclePointerV1)

    def _validate_pair(
        self, result: MonitoringCycleResultV1, alerts: MonitoringAlertBatchV1
    ) -> None:
        if result.alert_batch_id != alerts.alert_batch_id:
            raise MonitoringCycleStoreError("cycle result and alert batch identities differ")
        if result.alert_batch_content_sha256 != alerts.content_sha256:
            raise MonitoringCycleStoreError("cycle result and alert batch hashes differ")
        if result.cycle_id != alerts.cycle_id or result.watchlist_id != alerts.watchlist_id:
            raise MonitoringCycleStoreError("cycle result and alert batch scope differs")

    def publish(
        self,
        result: MonitoringCycleResultV1,
        alerts: MonitoringAlertBatchV1,
    ) -> MonitoringCyclePointerV1:
        """Persist the immutable outbox/result pair, then atomically publish it."""

        self._validate_pair(result, alerts)
        self.save_alert_batch(alerts)
        self.save_result(result)
        pointer = MonitoringCyclePointerV1.build(
            cycle_id=result.cycle_id,
            result_content_sha256=result.content_sha256,
            alert_batch_id=alerts.alert_batch_id,
            alert_batch_content_sha256=alerts.content_sha256,
        )
        self._commit_bytes(
            self.pointer_path(result.cycle_id),
            canonical_json_bytes(pointer.model_dump(mode="json", warnings=False)) + b"\n",
            "pointer",
        )
        return pointer

    def _load_valid_published_pair(
        self, cycle_id: str, *, require_pointer: bool
    ) -> tuple[MonitoringCycleResultV1, MonitoringAlertBatchV1, MonitoringCyclePointerV1 | None]:
        result = self.load_result(cycle_id)
        alerts = self.load_alert_batch(result.alert_batch_id)
        self._validate_pair(result, alerts)
        pointer = None
        if self.pointer_path(cycle_id).exists():
            pointer = self.load_pointer(cycle_id)
            if (
                pointer.cycle_id != cycle_id
                or pointer.result_content_sha256 != result.content_sha256
                or pointer.alert_batch_id != alerts.alert_batch_id
                or pointer.alert_batch_content_sha256 != alerts.content_sha256
            ):
                raise MonitoringCycleStoreError(
                    "cycle latest pointer does not match immutable artifacts"
                )
        elif require_pointer:
            raise MonitoringCycleStoreError("cycle latest pointer is missing")
        return result, alerts, pointer

    def load_terminal(
        self, cycle_id: str, *, repair_pointer: bool = True
    ) -> tuple[MonitoringCycleResultV1, MonitoringAlertBatchV1] | None:
        """Load a terminal result, repairing a pointer-only crash when safe."""

        if not self.result_path(cycle_id).exists():
            return None
        result, alerts, pointer = self._load_valid_published_pair(cycle_id, require_pointer=False)
        if pointer is None and repair_pointer:
            pointer_model = MonitoringCyclePointerV1.build(
                cycle_id=result.cycle_id,
                result_content_sha256=result.content_sha256,
                alert_batch_id=alerts.alert_batch_id,
                alert_batch_content_sha256=alerts.content_sha256,
            )
            self._commit_bytes(
                self.pointer_path(cycle_id),
                canonical_json_bytes(pointer_model.model_dump(mode="json", warnings=False)) + b"\n",
                "pointer",
            )
        return result, alerts

    def load_status(self, cycle_id: str) -> dict[str, object] | None:
        pair = self.load_terminal(cycle_id, repair_pointer=False)
        if pair is None:
            return None
        result, alerts = pair
        return {
            "cycle": result,
            "alert_batch": alerts,
            "pointer_published": self.pointer_path(cycle_id).exists(),
        }


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CycleWriteKind",
    "FailureInjector",
    "MonitoringCycleStore",
    "MonitoringCycleStoreError",
]
