"""Session-owned asynchronous audit logging for simulation events."""

from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_FIELDS = (
    "timestamp", "level", "run_id", "record_kind", "operation", "event_type",
    "event_time", "vehicle_id", "plate", "authorized_space_id", "space_id",
    "reason", "threadName", "processName", "exception_type", "traceback",
)


def _utc_millis(value: float | None = None) -> str:
    instant = datetime.now(timezone.utc) if value is None else datetime.fromtimestamp(value, timezone.utc)
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe(value: Any) -> str:
    if value is None:
        return "-"
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


class _AuditFileHandler(logging.FileHandler):
    def __init__(self, filename: Path, owner: "AuditSession") -> None:
        self._owner = owner
        super().__init__(filename, encoding="utf-8", delay=False)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
            self.flush()
        except BaseException as error:
            self._owner._mark_failed("file handler", error)

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exc_info()[1] or OSError("unknown file handler failure")
        self._owner._mark_failed("file handler", error)


class _AuditQueueHandler(logging.handlers.QueueHandler):
    def __init__(self, records: queue.Queue, owner: "AuditSession") -> None:
        self._owner = owner
        super().__init__(records)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.enqueue(self.prepare(record))
        except BaseException as error:
            self._owner._mark_failed("audit queue", error)


class AuditSession:
    """Own one logging queue, listener, file, and temporary thread exception hook."""

    def __init__(self, directory: str | Path = "logs") -> None:
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"parking-{uuid.uuid4()}.log"
        self._lock = threading.RLock()
        self._records: queue.Queue = queue.Queue()
        self._failed = False
        self._closed = False
        self._active_run_id: str | None = None
        self._logger = logging.Logger(f"parking.audit.{uuid.uuid4()}", logging.INFO)
        self._queue_handler = _AuditQueueHandler(self._records, self)
        self._logger.addHandler(self._queue_handler)
        self._file_handler = _AuditFileHandler(self.path, self)
        self._file_handler.setFormatter(logging.Formatter("\t".join(f"{name}=%({name})s" for name in _FIELDS)))
        self._listener = logging.handlers.QueueListener(self._records, self._file_handler)
        self._previous_hook = threading.excepthook
        self._hook = self._thread_exception
        threading.excepthook = self._hook
        try:
            self._listener.start()
            self._listener_thread = self._listener._thread
        except BaseException:
            threading.excepthook = self._previous_hook
            self._file_handler.close()
            raise

    @property
    def audit_complete(self) -> bool:
        with self._lock:
            return not self._failed and self._closed

    @property
    def audit_failed(self) -> bool:
        with self._lock:
            return self._failed

    def begin_run(self) -> str:
        with self._lock:
            run_id = str(uuid.uuid4())
            self._active_run_id = run_id
            return run_id

    def end_run(self, run_id: str) -> None:
        with self._lock:
            if self._active_run_id == run_id:
                self._active_run_id = None

    def event(self, event: Any, run_id: str) -> None:
        self._log("INFO", "event", run_id, event_type=event.type,
                  event_time=_utc_millis(event.timestamp), vehicle_id=event.vehicle_id,
                  plate=event.plate, authorized_space_id=event.authorized_space_id,
                  space_id=event.space_id, reason=event.reason)

    def operation(self, operation: str, run_id: str, *, vehicle_id=None, plate=None) -> None:
        self._log("INFO", "operation", run_id, operation=operation, vehicle_id=vehicle_id, plate=plate)

    def exception(self, operation: str, run_id: str | None, error: BaseException) -> None:
        self._log("ERROR", "exception", run_id, operation=operation,
                  exception_type=type(error).__name__, traceback="".join(
                      traceback.format_exception(type(error), error, error.__traceback__)))

    def _log(self, level: str, kind: str, run_id: str | None, **values: Any) -> None:
        fields = dict.fromkeys(_FIELDS, "-")
        fields.update(timestamp=_utc_millis(), level=level, run_id=run_id or "-",
                      record_kind=kind, threadName=threading.current_thread().name)
        fields.update({key: _safe(value) for key, value in values.items()})
        record = logging.LogRecord(
            self._logger.name,
            getattr(logging, level),
            __file__,
            0,
            "\t".join(f"{name}=%({name})s" for name in _FIELDS),
            (),
            None,
        )
        fields["processName"] = record.processName
        for key, value in fields.items():
            setattr(record, key, value)
        self._logger.handle(record)

    def _thread_exception(self, args: threading.ExceptHookArgs) -> None:
        if threading.current_thread() is self._listener_thread:
            self._mark_failed("listener thread", args.exc_value)
            self._previous_hook(args)
            return
        with self._lock:
            run_id = self._active_run_id
        if getattr(threading.current_thread(), "_parking_audit_logged", False):
            self._previous_hook(args)
            return
        try:
            self.exception("thread_uncaught", run_id, args.exc_value)
        except BaseException as error:
            self._mark_failed("thread exception hook", error)
        self._previous_hook(args)

    def _mark_failed(self, where: str, error: BaseException) -> None:
        with self._lock:
            self._failed = True
        try:
            sys.stderr.write(f"Parking audit incomplete ({where}): {type(error).__name__}: {error}\n")
            sys.stderr.flush()
        except BaseException:
            pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
        # The caller must drain Simulator/ParkingLot workers before this point.
        self._logger.removeHandler(self._queue_handler)
        self._queue_handler.close()
        stop_error = None
        try:
            self._listener.stop()
        except BaseException as error:
            stop_error = error
            self._mark_failed("listener shutdown", error)
        if threading.excepthook is self._hook:
            threading.excepthook = self._previous_hook
        try:
            self._file_handler.flush()
        except BaseException as error:
            self._mark_failed("final flush", error)
        self._file_handler.close()
        with self._lock:
            self._closed = True
        if stop_error is not None:
            raise stop_error
