"""Simulation orchestration."""

from __future__ import annotations

import random
from threading import Event, Lock, Thread
from time import time
from typing import TYPE_CHECKING, Callable

from core.events import SIMULATION_FINISHED, SIMULATION_STARTED, ParkingEvent
from core.vehicle import Vehicle
from simulation import config
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics

if TYPE_CHECKING:
    from core.parking import ParkingLot


class Simulator:
    """Generates vehicle arrivals and drives the simulation lifecycle.

    Runs its own background thread so callers such as the Tkinter UI thread
    never block while vehicles are generated; vehicles remain the only
    threads representing OS-level concurrent work.
    """

    def __init__(self, run_factory: Callable[[], tuple[ParkingLot, MetricsForwardingQueue,
                                                      SimulationMetrics]]) -> None:
        self._run_factory = run_factory
        self._state_lock = Lock()
        self._stop_requested: Event | None = None
        self._thread: Thread | None = None
        self._drained = True
        self.metrics: SimulationMetrics | None = None

    def start(self) -> bool:
        """Accept a new run only after the previous thread has exited."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            # A failed close cannot be mistaken for a reusable, finished run.
            if self._thread is not None and not self._drained:
                return False
            parking, event_queue, metrics = self._run_factory()
            stop_requested = Event()
            thread = Thread(target=self._run,
                            args=(parking, event_queue, metrics, stop_requested))
            self._drained = False
            try:
                thread.start()
            except BaseException:
                self._drained = True
                raise
            self._stop_requested = stop_requested
            self.metrics = metrics
            self._thread = thread
            return True

    def stop(self) -> None:
        """Request early termination of the simulation.

        Vehicles already parked or waiting are allowed to finish through
        `ParkingLot.close`; no thread is terminated forcibly.
        """
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                self._stop_requested.set()

    def is_active(self) -> bool:
        with self._state_lock:
            return self._thread is not None and self._thread.is_alive()

    def is_drained(self) -> bool:
        with self._state_lock:
            return self._drained

    def _run(self, parking: ParkingLot, event_queue: MetricsForwardingQueue,
             metrics: SimulationMetrics, stop_requested: Event) -> None:
        try:
            event_queue.put(ParkingEvent(type=SIMULATION_STARTED, timestamp=time()))
            for vehicle_id in range(1, config.TOTAL_VEHICLES + 1):
                arrival_delay = random.uniform(config.MIN_ARRIVAL_TIME, config.MAX_ARRIVAL_TIME)
                if stop_requested.wait(arrival_delay):
                    break

                # stop() and this admission share one boundary: once stop returns,
                # no new vehicle can be constructed or admitted for this run.
                with self._state_lock:
                    if stop_requested.is_set():
                        break
                    parking_duration = random.uniform(config.MIN_PARKING_TIME,
                                                      config.MAX_PARKING_TIME)
                    vehicle = Vehicle(vehicle_id=vehicle_id, parking=parking,
                                      parking_duration=parking_duration)
                    metrics.record_generated()
                    if parking.admit(vehicle):
                        metrics.record_admitted()
                    else:
                        metrics.record_rejected()
        finally:
            # Join only on the background thread. Workers publish terminal
            # events before the final lifecycle event reaches the UI queue.
            parking.close(wait=True)
            with self._state_lock:
                self._drained = True
            event_queue.put(ParkingEvent(type=SIMULATION_FINISHED, timestamp=time()))
