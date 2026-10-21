"""Simulation producer and run lifecycle orchestration."""

from __future__ import annotations

import random
from threading import Event, Lock, Thread
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

    def start(self) -> bool:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self._thread is not None and not self._drained:
                return False
            parking, event_queue, metrics = self._run_factory()
            self._stop_requested = Event()
            self._drained = False
            self._parking = parking
            self.metrics = metrics
            try:
                parking.start()
                thread = Thread(target=self._run, args=(parking, event_queue, metrics,
                                                        self._stop_requested), name="simulation-producer")
                thread.start()
            except BaseException:
                parking.close(wait=True)
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
        if parking is not None:
            parking.close(wait=False)

    def is_active(self) -> bool:
        with self._state_lock:
            return self._thread is not None and self._thread.is_alive()

    def is_drained(self) -> bool:
        with self._state_lock:
            return self._drained

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
                result = parking.admit(vehicle)
                if result.accepted:
                    metrics.record_admitted()
                else:
                    metrics.record_rejected()
            parking.close(wait=True, cancel_pending=stop_requested.is_set())
            event_queue.put(ParkingEvent(type=SIMULATION_FINISHED, timestamp=time()))
            with self._state_lock:
                self._drained = True
            succeeded = True
        finally:
            if not succeeded:
                try:
                    parking.close(wait=True)
                except BaseException:
                    pass
