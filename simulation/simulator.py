"""Simulation producer and run lifecycle orchestration."""

from __future__ import annotations

import random
import sys
from threading import Event, Lock, Thread, current_thread
from time import time
from typing import Callable, Sequence

from core.events import SIMULATION_FINISHED, SIMULATION_STARTED, ParkingEvent
from core.vehicle import Vehicle
from simulation import config
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics


class Simulator:
    def __init__(self, run_factory: Callable, plate_sequence: Sequence[str],
                 duration_factory: Callable[[], float] | None = None) -> None:
        self._run_factory = run_factory
        self._plate_sequence = tuple(plate_sequence)
        self._duration_factory = duration_factory or (
            lambda: random.uniform(config.MIN_PARKING_TIME, config.MAX_PARKING_TIME))
        self._state_lock = Lock()
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._parking = None
        self._drained = True
        self.metrics: SimulationMetrics | None = None
        self._audit = None
        self._run_id: str | None = None
        self._stop_logged = False

    def set_audit(self, audit) -> None:
        """Attach the app-session audit sink before starting the application."""
        self._audit = audit

    def start(self) -> bool:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self._thread is not None and not self._drained:
                return False
            try:
                parking, event_queue, metrics = self._run_factory()
            except BaseException as error:
                if self._audit is not None:
                    self._audit.exception("run_setup", "-", error)
                raise
            run_id = self._audit.begin_run() if self._audit is not None else None
            self._run_id = run_id
            self._stop_logged = False
            if hasattr(event_queue, "set_audit_context") and run_id is not None:
                event_queue.set_audit_context(self._audit, run_id)
            self._stop_requested = Event()
            self._drained = False
            self._parking = parking
            self.metrics = metrics
            try:
                parking.start()
                thread = Thread(target=self._run_with_audit, args=(parking, event_queue, metrics,
                                                                   self._stop_requested, run_id),
                                name="simulation-producer")
                thread.start()
            except BaseException as start_error:
                if self._audit is not None:
                    self._audit.exception("simulator_start", run_id, start_error)
                try:
                    parking.close(wait=True)
                except BaseException as cleanup_error:
                    if self._audit is not None:
                        self._audit.exception("startup_cleanup", run_id, cleanup_error)
                if self._audit is not None:
                    self._audit.end_run(run_id)
                self._drained = True
                self._parking = None
                raise
            self._thread = thread
            return True

    def stop(self) -> None:
        with self._state_lock:
            parking = self._parking
            thread = self._thread
            if thread is None or not thread.is_alive():
                return
            # Publish stop intent before calling into core. ParkingLot.close()
            # linearizes against admit() under its Condition: a commit that
            # wins that lock is already accepted work to drain; later commits
            # observe LOT_CLOSED. The producer checks this intent before its
            # next generation/admission attempt.
            self._stop_requested.set()
            if not self._stop_logged and self._audit is not None and self._run_id is not None:
                self._audit.operation("stop_requested", self._run_id)
                self._stop_logged = True
        if parking is not None:
            try:
                parking.close(wait=False)
            except BaseException as error:
                if self._audit is not None:
                    self._audit.exception("stop_failure", self._run_id, error)
                raise

    def is_active(self) -> bool:
        with self._state_lock:
            return self._thread is not None and self._thread.is_alive()

    def is_drained(self) -> bool:
        with self._state_lock:
            return self._drained

    def shutdown(self) -> None:
        """Request stop and join the producer before the app audit listener closes."""
        stop_error = None
        try:
            self.stop()
        except BaseException as error:
            stop_error = error
        with self._state_lock:
            thread = self._thread
        if thread is not None:
            thread.join()
        if stop_error is not None:
            raise stop_error

    def _run(self, parking, event_queue: MetricsForwardingQueue,
             metrics: SimulationMetrics, stop_requested: Event) -> None:
        succeeded = False
        try:
            event_queue.put(ParkingEvent(type=SIMULATION_STARTED, timestamp=time()))
            for vehicle_id, plate in enumerate(self._plate_sequence, start=1):
                if stop_requested.wait(random.uniform(config.MIN_ARRIVAL_TIME,
                                                      config.MAX_ARRIVAL_TIME)):
                    break
                if stop_requested.is_set():
                    break
                duration = self._duration_factory()
                vehicle = Vehicle(vehicle_id, parking, duration, plate)
                metrics.record_generated()
                if self._audit is not None and self._run_id is not None:
                    self._audit.operation("admission_attempt", self._run_id,
                                          vehicle_id=vehicle_id, plate=plate)
                result = parking.admit(vehicle)
                if result.accepted:
                    metrics.record_admitted()
            parking.close(wait=True, cancel_pending=stop_requested.is_set())
            event_queue.put(ParkingEvent(type=SIMULATION_FINISHED, timestamp=time()))
            with self._state_lock:
                self._drained = True
            succeeded = True
        finally:
            if not succeeded:
                primary_error = sys.exc_info()[1]
                try:
                    parking.close(wait=True)
                except BaseException as cleanup_error:
                    if (self._audit is not None
                            and not _shares_exception_cause(primary_error, cleanup_error)):
                        self._audit.exception("producer_cleanup", self._run_id, cleanup_error)
            if self._audit is not None and self._run_id is not None:
                self._audit.end_run(self._run_id)

    def _run_with_audit(self, parking, event_queue, metrics, stop_requested, run_id) -> None:
        try:
            self._run(parking, event_queue, metrics, stop_requested)
        except BaseException as error:
            if self._audit is not None:
                self._audit.exception("producer_uncaught", run_id, error)
            # The thread exception hook delegates to the previous hook but
            # avoids writing this same exception a second time.
            current_thread()._parking_audit_logged = True
            raise


def _shares_exception_cause(first: BaseException | None, second: BaseException) -> bool:
    """Detect cleanup errors that only repeat the active primary failure."""
    if first is None:
        return False
    first_chain = {id(error) for error in _exception_chain(first)}
    return any(id(error) in first_chain for error in _exception_chain(second))


def _exception_chain(error: BaseException):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__
