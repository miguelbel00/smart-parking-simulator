"""Simulation orchestration."""

from __future__ import annotations

import random
from threading import Event, Thread
from time import time
from typing import TYPE_CHECKING, Any

from core.events import SIMULATION_FINISHED, SIMULATION_STARTED, ParkingEvent
from core.vehicle import Vehicle
from simulation import config
from simulation.metrics import SimulationMetrics

if TYPE_CHECKING:
    from core.parking import ParkingLot


class Simulator:
    """Generates vehicle arrivals and drives the simulation lifecycle.

    Runs its own background thread so callers such as the Tkinter UI thread
    never block while vehicles are generated; vehicles remain the only
    threads representing OS-level concurrent work.
    """

    def __init__(self, parking: ParkingLot, event_queue: Any,
                 metrics: SimulationMetrics | None = None) -> None:
        self._parking = parking
        self._event_queue = event_queue
        self.metrics = metrics if metrics is not None else SimulationMetrics()
        self._stop_requested = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start vehicle generation in a background thread. Non-blocking."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Request early termination of the simulation.

        Vehicles already parked or waiting are allowed to finish through
        `ParkingLot.close`; no thread is terminated forcibly.
        """
        self._stop_requested.set()

    def _run(self) -> None:
        self._event_queue.put(ParkingEvent(type=SIMULATION_STARTED, timestamp=time()))

        for vehicle_id in range(1, config.TOTAL_VEHICLES + 1):
            if self._stop_requested.is_set():
                break

            arrival_delay = random.uniform(config.MIN_ARRIVAL_TIME, config.MAX_ARRIVAL_TIME)
            if self._stop_requested.wait(arrival_delay):
                break

            parking_duration = random.uniform(config.MIN_PARKING_TIME, config.MAX_PARKING_TIME)
            vehicle = Vehicle(vehicle_id=vehicle_id, parking=self._parking,
                              parking_duration=parking_duration)
            self.metrics.record_generated()

            if self._parking.admit(vehicle):
                self.metrics.record_admitted()
            else:
                self.metrics.record_rejected()

        self._parking.close(wait=True)
        self._event_queue.put(ParkingEvent(type=SIMULATION_FINISHED, timestamp=time()))
