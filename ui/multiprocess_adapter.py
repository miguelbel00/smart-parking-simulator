"""Asynchronous parent-side bridge from multiprocessing IPC to the Tk queue."""

from __future__ import annotations

import queue
import threading
import uuid

from core.events import ParkingEvent
from simulation.ipc_protocol import parking_event_from_message
from simulation.metrics import SimulationMetrics


class MultiprocessGUIAdapter:
    """Keep all blocking controller operations on a transport worker thread."""

    def __init__(self, controller, event_queue, payload_factory) -> None:
        self.controller = controller
        self.event_queue = event_queue
        self._payload_factory = payload_factory
        self._commands: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._transport, name="parking-ipc-transport", daemon=True)
        self._started = False
        self._stopping = False
        self._shutdown_sent = False
        self._active = False
        self._drained = True
        self._closed = False
        self._cleanup_complete = False
        self._error: BaseException | None = None
        self._run_id: str | None = None
        self._projected_events: set[tuple[str, int]] = set()
        self.metrics: SimulationMetrics | None = None

    def start_engine(self) -> None:
        self._thread.start()
        self._started = True

    def start(self) -> bool:
        if self._closed or self._stopping or self._active or not self._drained:
            return False
        run_id = str(uuid.uuid4())
        metrics = SimulationMetrics()
        self._run_id, self.metrics = run_id, metrics
        self._active, self._drained = True, False
        self._commands.put(("START", run_id, self._payload_factory(), metrics))
        return True

    def stop(self) -> None:
        if self._active and self._run_id is not None:
            self._commands.put(("STOP", self._run_id, None, None))

    def is_active(self) -> bool:
        return self._active

    def is_drained(self) -> bool:
        return self._drained

    @property
    def shutdown_complete(self) -> bool:
        return self._closed and self._error is None

    @property
    def cleanup_complete(self) -> bool:
        """Whether bounded cleanup verified child exit and audit closure."""
        return self._cleanup_complete

    @property
    def error(self):
        return self._error

    def shutdown_async(self) -> None:
        if not self._stopping:
            self._stopping = True
            if self._active:
                self._commands.put(("STOP", self._run_id, None, None))

    def _transport(self) -> None:
        try:
            self.controller.start_engine()
            while not self._closed:
                try:
                    command = self._commands.get(timeout=0.02)
                except queue.Empty:
                    command = None
                if command is not None:
                    name, run_id, payload, metrics = command
                    if name == "START":
                        started_run_id = self.controller.start(payload, run_id=run_id)
                        if started_run_id != run_id:
                            raise RuntimeError("engine did not accept START")
                        self._results.put(("START_ACCEPTED", run_id, None))
                    elif name == "STOP":
                        self.controller.stop(run_id)
                if not self._closed:
                    self._drain_one()
                if self._stopping and self._drained and not self._shutdown_sent:
                    self._shutdown_sent = True
                    self.controller.shutdown()
                    audit = getattr(self.controller, "_audit", None)
                    if audit is not None and not audit.confirm():
                        raise RuntimeError("audit drain was not confirmed")
                    if audit is not None:
                        audit.close()
                        if not getattr(audit, "_closed", False):
                            raise RuntimeError("audit close was not confirmed")
                    if self.controller.is_alive():
                        raise RuntimeError("engine exit was not confirmed")
                    self._results.put(("CLEANUP_COMPLETE", None, None))
                    self._closed = True
                    self._cleanup_complete = True
        except BaseException as error:
            self._error = error
            self._active = False
            self._drained = False
            self._results.put(("ERROR", self._run_id, error))
            # A transport failure invalidates run/audit success, but the child
            # still needs a bounded best-effort shutdown attempt.
            try:
                self.controller.shutdown()
                child_exited = not self.controller.is_alive()
                audit = getattr(self.controller, "_audit", None)
                if audit is not None:
                    audit.confirm()
                    audit.close()
                audit_closed = audit is None or bool(getattr(audit, "_closed", False))
                if child_exited and audit_closed:
                    # Cleanup may permit window closure, never run success.
                    self._cleanup_complete = True
                    self._results.put(("CLEANUP_COMPLETE", None, None))
            except BaseException as cleanup_error:
                self._results.put(("ERROR", self._run_id, cleanup_error))

    def _drain_one(self) -> None:
        try:
            message = self.controller.get(block=False)
        except queue.Empty:
            return
        if message["kind"] == "event":
            run_id = message["run_id"]
            if run_id != self._run_id:
                raise RuntimeError("received event for a non-current run")
            key = (run_id, message["seq"])
            if key in self._projected_events:
                return
            self._projected_events.add(key)
            event = parking_event_from_message(message)
            if self.metrics is not None:
                if event.type in {"VEHICLE_CREATED", "VEHICLE_REJECTED"}:
                    self.metrics.record_generated()
                if event.type == "VEHICLE_CREATED":
                    self.metrics.record_admitted()
                self.metrics.record_event(event)
            self.event_queue.put(event)
            if event.type == "SIMULATION_FINISHED":
                self._active, self._drained = False, True
        elif message["kind"] == "failure":
            raise RuntimeError(f"engine failure: {message['error']}")

    def poll_results(self, limit: int = 32) -> list[tuple[str, str | None, BaseException | None]]:
        results = []
        for _ in range(limit):
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results
