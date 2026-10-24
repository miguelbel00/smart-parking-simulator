"""Spawn-based process controller and parking simulation engine."""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time
import traceback
from threading import Lock
from typing import Any

from core.parking import ParkingLot
from simulation import config
from simulation.audit_logging import AuditSession
from simulation.authorizations import Authorization, AuthorizationRegistry
from simulation.ipc_protocol import (
    parking_event_from_message,
    parking_event_to_message,
    validate_message,
    validate_start_payload,
)
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator


def _origin() -> dict[str, Any]:
    return {"process_id": os.getpid(), "process_name": mp.current_process().name,
            "thread_name": threading.current_thread().name}


class _Publisher:
    """Serialize all process event publications before using the bounded IPC queue."""

    def __init__(self, destination, run_id: str, timeout: float = 0.25, failure_signal=None) -> None:
        self._destination = destination
        self._run_id = run_id
        self._sequence = 0
        self._audit_sequence = 0
        self._timeout = timeout
        self._failure_signal = failure_signal
        self._lock = Lock()
        self.dropped = 0
        self.failed = False

    def put(self, event, block: bool = True, timeout: float | None = None) -> None:
        self.put_with_origin(event, _origin(), block=block, timeout=timeout)

    def put_with_origin(self, event, origin: dict[str, Any],
                        block: bool = True, timeout: float | None = None) -> None:
        with self._lock:
            self._raise_if_failed()
            message = parking_event_to_message(event, self._run_id, self._sequence, origin=origin)
            self._send(message)

    def audit(self, name: str, payload: dict[str, Any], timestamp: float | None = None) -> None:
        with self._lock:
            self._raise_if_failed()
            message = {"v": 1, "kind": "audit", "run_id": self._run_id,
                       "seq": self._audit_sequence, "name": name,
                       "timestamp": time.time() if timestamp is None else timestamp,
                       "payload": payload}
            validate_message(message)
            self._send(message)

    def _send(self, message: dict[str, Any]) -> None:
        if message["kind"] == "event":
            self._sequence += 1
        else:
            self._audit_sequence += 1
        try:
            self._destination.put(message, timeout=self._timeout)
        except queue.Full:
            self.dropped += 1
            self.failed = True
            if self._failure_signal is not None:
                self._failure_signal.set()
            raise RuntimeError("IPC output queue remained full")

    def _raise_if_failed(self) -> None:
        if self.failed:
            raise RuntimeError("IPC publisher failed; run is incomplete")


class _ChildAudit:
    """Forward child audit calls through IPC; never opens a child log file."""

    def __init__(self, publisher: _Publisher) -> None:
        self._publisher = publisher

    def operation(self, operation: str, run_id: str, *, vehicle_id=None, plate=None) -> None:
        self._audit("REQUEST", {"record_kind": "operation", "operation": operation,
                                 "vehicle_id": vehicle_id, "plate": plate})

    def event(self, event, run_id: str, *, origin=None) -> None:
        # The event itself is already published through the same ordered publisher.
        pass

    def exception(self, operation: str, run_id: str | None, error: BaseException) -> None:
        self._audit("ERROR", {"record_kind": "exception", "operation": operation,
                               "exception_type": type(error).__name__,
                               "error": "".join(traceback.format_exception_only(type(error), error))[:1000]})

    def _audit(self, name: str, payload: dict[str, Any]) -> None:
        origin = _origin()
        payload = {**payload, "origin_process_id": origin["process_id"],
                   "origin_process_name": origin["process_name"],
                   "origin_thread_name": origin["thread_name"]}
        try:
            self._publisher.audit(name, payload)
        except RuntimeError:
            if not self._publisher.failed:
                raise

    def begin_run(self, run_id: str) -> str:
        return run_id

    def end_run(self, run_id: str) -> None:
        pass


def _engine(command_queue, output_queue, transport_failed) -> None:
    active: dict[str, Simulator] = {}
    shutdown = False
    while not shutdown:
        command = command_queue.get()
        _reap_finished(active)
        try:
            validate_message(command)
            name = command["name"]
            run_id = command["run_id"]
            if name == "SHUTDOWN":
                _reap_finished(active)
                for simulator in tuple(active.values()):
                    simulator.stop()
                for simulator in tuple(active.values()):
                    simulator.shutdown()
                active.clear()
                _put_bounded(output_queue, _reply(command, "accepted"))
                shutdown = True
                continue
            if name == "STOP":
                simulator = active.get(run_id)
                if simulator is None:
                    reply = _reply(command, "rejected", "UNKNOWN_RUN")
                else:
                    simulator.stop()
                    reply = _reply(command, "accepted")
                _put_bounded(output_queue, reply)
                continue
            if run_id in active:
                _put_bounded(output_queue, _reply(command, "rejected", "DUPLICATE_RUN"))
                continue
            payload = command["payload"]
            values = payload["config"]
            config.PARKING_CAPACITY = values["capacity"]
            config.TOTAL_VEHICLES = values["total_vehicles"]
            config.MIN_ARRIVAL_TIME = values["min_arrival_time"]
            config.MAX_ARRIVAL_TIME = values["max_arrival_time"]
            config.MIN_PARKING_TIME = values["min_parking_time"]
            config.MAX_PARKING_TIME = values["max_parking_time"]
            registry = AuthorizationRegistry({
                record["plate"].strip().upper(): Authorization(
                    record["plate"].strip().upper(), record["authorized"], record["space_id"]
                ) for record in payload["authorization"]["vehicles"]
            })
            transport_failed.clear()
            publisher = _Publisher(output_queue, run_id, failure_signal=transport_failed)
            metrics = SimulationMetrics()

            def run_factory():
                forwarding = MetricsForwardingQueue(destination=publisher, metrics=metrics)
                parking = ParkingLot(values["capacity"], forwarding, registry)
                return parking, forwarding, metrics

            simulator = Simulator(run_factory, payload["plate_sequence"])
            simulator.set_audit(_ChildAudit(publisher))
            if not simulator.start(run_id=run_id):
                _put_bounded(output_queue, _reply(command, "rejected", "BUSY"))
                continue
            active[run_id] = simulator
            _put_bounded(output_queue, _reply(command, "accepted"))
        except BaseException:
            # A full bounded queue must not make the child wait forever for
            # its feeder thread while exiting after a transport failure.
            if transport_failed.is_set():
                output_queue.cancel_join_thread()
            _put_bounded(output_queue, {"v": 1, "kind": "failure", "run_id": command.get("run_id"),
                                        "name": "ENGINE_FAILED", "error": "WORKER_FAILED"})
            raise


def _reap_finished(active: dict[str, Simulator]) -> None:
    """Drop only simulators whose parking workers and producer have exited."""
    for run_id, simulator in tuple(active.items()):
        if simulator.is_drained() and not simulator.is_active():
            del active[run_id]


def _reply(command: dict[str, Any], status: str, reason: str | None = None) -> dict[str, Any]:
    result = {"v": 1, "kind": "reply", "run_id": command["run_id"],
              "command": command["name"], "request_id": command["request_id"], "status": status}
    if reason is not None:
        result["reason"] = reason
    return result


def _put_bounded(destination, message: dict[str, Any], timeout: float = 0.25) -> bool:
    try:
        destination.put(message, timeout=timeout)
        return True
    except queue.Full:
        return False


class MultiprocessController:
    """Parent-side bounded-queue controller; the parent remains audit owner."""

    def __init__(self, capacity: int, queue_size: int = 256, audit: AuditSession | None = None,
                 context: str = "spawn") -> None:
        if type(queue_size) is not int or queue_size < 1:
            raise ValueError("queue_size must be positive")
        self._context = mp.get_context(context)
        self._capacity = capacity
        self._audit = audit
        self._commands = self._context.Queue(maxsize=queue_size)
        self._output = self._context.Queue(maxsize=queue_size)
        self._transport_failed = self._context.Event()
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be positive")
        self._process = self._context.Process(target=_engine, args=(self._commands, self._output, self._transport_failed),
                                              name="parking-engine")
        self._request = 0
        self._run_sequence = 0
        self._runs: set[str] = set()
        self._pending: list[dict[str, Any]] = []
        self._finished: set[str] = set()
        self._terminal_received: set[str] = set()
        self._terminal: dict[str, set[int]] = {}
        self._created: dict[str, set[int]] = {}
        self._seen_events: set[tuple[str, int]] = set()
        self._seen_audits: set[tuple[str | None, int]] = set()
        self._next_event_seq: dict[str, int] = {}
        self._next_audit_seq: dict[str | None, int] = {}
        self._timeout = 10.0

    def start_engine(self) -> None:
        self._process.start()

    def start(self, payload: dict[str, Any], run_id: str | None = None) -> str:
        self._ensure_engine()
        validate_start_payload(payload)
        if payload["config"]["capacity"] != self._capacity:
            raise ValueError("START capacity does not match controller capacity")
        if any(existing not in self._terminal_received for existing in self._runs):
            raise RuntimeError("a run is already active")
        if run_id is None:
            # IDs remain unique for this controller lifetime, including supplied IDs.
            self._run_sequence += 1
            while f"run-{self._run_sequence}" in self._runs:
                self._run_sequence += 1
            run_id = f"run-{self._run_sequence}"
        elif run_id in self._runs:
            raise RuntimeError("run ID has already been used")
        if self._audit is not None:
            self._audit.begin_run(run_id)
            self._audit.operation("run_requested", run_id)
        self._runs.add(run_id)
        self._terminal[run_id] = set()
        self._created[run_id] = set()
        self._expected[run_id] = payload["config"]["total_vehicles"]
        reply = self._command("START", run_id, payload)
        if reply["status"] != "accepted":
            raise RuntimeError(f"START rejected: {reply.get('reason')}")
        return run_id

    def stop(self, run_id: str) -> None:
        if self._audit is not None:
            self._audit.operation("stop_requested", run_id)
        reply = self._command("STOP", run_id)
        if reply["status"] != "accepted":
            raise RuntimeError(f"STOP rejected: {reply.get('reason')}")

    def shutdown(self) -> None:
        # Transport failure invalidates run output, not the cleanup command.
        # Keep consuming stale messages so a bounded output queue cannot stop
        # the engine from publishing its shutdown reply.
        try:
            self._command("SHUTDOWN", None, cleanup=True)
        finally:
            self._process.join(self._timeout)
            if self._process.is_alive():
                raise TimeoutError("engine did not stop after shutdown")

    def get(self, block: bool = True, timeout: float | None = None) -> dict[str, Any]:
        self._raise_if_transport_failed()
        if self._pending:
            message = self._pending.pop(0)
        else:
            wait = self._timeout if block and timeout is None else timeout
            try:
                message = self._output.get(block=block, timeout=wait)
            except queue.Empty:
                self._ensure_engine()
                raise
        if message.get("kind") == "event":
            self._handle_event(message)
        elif message.get("kind") == "audit":
            self._handle_audit(message)
        elif message.get("kind") in {"reply", "failure"}:
            validate_message(message)
        self._raise_if_transport_failed()
        return message

    def _raise_if_transport_failed(self) -> None:
        if self._transport_failed.is_set():
            if self._audit is not None:
                self._audit._mark_failed("IPC transport", RuntimeError("shared transport failure"))
            raise RuntimeError("engine IPC transport failed; run is incomplete")

    def join(self, timeout: float | None = None) -> None:
        self._process.join(timeout)

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def _send(self, name: str, run_id: str | None, payload: dict[str, Any] | None = None) -> None:
        self._request += 1
        message = {"v": 1, "kind": "command", "run_id": run_id,
                   "name": name, "request_id": f"req-{self._request}"}
        if payload is not None:
            message["payload"] = payload
        validate_message(message)
        deadline = time.monotonic() + self._timeout
        while True:
            self._ensure_engine()
            try:
                self._commands.put(message, timeout=min(.1, max(0, deadline-time.monotonic())))
                self._last_request = message
                return
            except queue.Full:
                if time.monotonic() >= deadline:
                    raise TimeoutError("engine command queue remained full")

    _expected: dict[str, int] = {}

    def _command(self, name, run_id, payload=None, cleanup=False):
        self._send(name, run_id, payload)
        request = self._last_request
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if not cleanup:
                self._raise_if_transport_failed()
            self._ensure_engine()
            match = next((item for item in self._pending
                          if item.get("kind") == "reply"
                          and item.get("request_id") == request["request_id"]), None)
            if match is not None:
                self._pending.remove(match)
                if match["command"] != name or match["run_id"] != run_id:
                    raise RuntimeError("engine reply correlation mismatch")
                if name == "SHUTDOWN":
                    self._pending.append(match)
                return match
            try:
                message = self._output.get(timeout=min(.1, max(0, deadline-time.monotonic())))
            except queue.Empty:
                continue
            if cleanup:
                if (message.get("kind") == "reply"
                        and message.get("request_id") == request["request_id"]):
                    if name == "SHUTDOWN":
                        self._pending.append(message)
                    return message
                # All run output is invalid after transport failure; discard it
                # rather than retaining messages in the bounded IPC channel.
                continue
            if message.get("kind") == "event":
                # Process audit effects now and retain the event for public get().
                self._handle_event(message)
                self._pending.append(message)
            elif message.get("kind") == "audit":
                self._handle_audit(message)
                self._pending.append(message)
            if message.get("kind") == "reply" and message["request_id"] == request["request_id"]:
                if message["command"] != name or message["run_id"] != run_id:
                    raise RuntimeError("engine reply correlation mismatch")
                if name == "SHUTDOWN":
                    self._pending.append(message)
                return message
            else:
                self._pending.append(message)
            if message.get("kind") == "failure":
                raise RuntimeError(f"engine failed: {message['error']}")
        raise TimeoutError(f"timed out waiting for {name} reply")

    def _handle_event(self, message):
        validate_message(message)
        key = (message["run_id"], message["seq"])
        if key in self._seen_events:
            return
        expected = self._next_event_seq.get(message["run_id"], 0)
        if message["seq"] != expected:
            if self._audit is not None:
                self._audit._mark_failed("IPC event sequence", RuntimeError("non-contiguous event sequence"))
            raise RuntimeError("non-contiguous event sequence; run is incomplete")
        self._next_event_seq[message["run_id"]] = expected + 1
        self._seen_events.add(key)
        event = parking_event_from_message(message)
        if self._audit is not None:
            metadata = message.get("origin")
            audit_origin = ({"origin_process_id": metadata["process_id"],
                             "origin_process_name": metadata["process_name"],
                             "origin_thread_name": metadata["thread_name"]}
                            if metadata is not None else None)
            self._audit.event(event, message["run_id"], origin=audit_origin)
            if event.type == "SIMULATION_FINISHED":
                self._audit.end_run(message["run_id"])
        run_id = message["run_id"]
        if message["name"] == "VEHICLE_CREATED":
            self._created.setdefault(run_id, set()).add(message["payload"]["vehicle_id"])
        elif message["name"] == "VEHICLE_REJECTED":
            self._created.setdefault(run_id, set()).add(message["payload"]["vehicle_id"])
        if message["name"] in {"VEHICLE_FINISHED", "VEHICLE_CANCELLED", "VEHICLE_REJECTED"}:
            self._terminal.setdefault(run_id, set()).add(message["payload"]["vehicle_id"])
        if message["name"] == "SIMULATION_FINISHED":
            if self._transport_failed.is_set():
                raise RuntimeError("engine IPC transport failed; run is incomplete")
            if self._terminal.get(run_id, set()) != self._created.get(run_id, set()):
                raise RuntimeError("normal completion missing vehicle terminal events")
            self._terminal_received.add(run_id)
            if self._audit is None:
                self._finished.add(run_id)
            elif not self._audit.audit_failed and self._audit.confirm(timeout=self._timeout):
                # The engine uses one serialized Publisher and this controller
                # handles its output sequentially, so the barrier covers all
                # earlier event/audit messages delivered for this run.
                self._finished.add(run_id)
            else:
                self._audit._mark_failed("simulation audit confirmation",
                                          RuntimeError("audit incomplete at simulation finish"))
                raise RuntimeError("audit incomplete; run success is unconfirmed")

    def _handle_audit(self, message):
        validate_message(message)
        key = (message["run_id"], message["seq"])
        if key in self._seen_audits:
            return
        expected = self._next_audit_seq.get(message["run_id"], 0)
        if message["seq"] != expected:
            if self._audit is not None:
                self._audit._mark_failed("IPC audit sequence", RuntimeError("non-contiguous audit sequence"))
            raise RuntimeError("non-contiguous audit sequence; audit is incomplete")
        self._next_audit_seq[message["run_id"]] = expected + 1
        self._seen_audits.add(key)
        if self._audit is not None:
            self._audit.audit_record(message)

    def _ensure_engine(self):
        if not self._process.is_alive() and self._process.exitcode is not None:
            raise RuntimeError("engine exited unexpectedly")
