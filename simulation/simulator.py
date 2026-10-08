"""Background vehicle generation for a public ParkingLot API."""

from __future__ import annotations

import random
from queue import Queue
from threading import Event, Lock, Thread
from time import time

from core.events import ParkingEvent, SIMULATION_FINISHED, SIMULATION_STARTED
from core.vehicle import Vehicle
from simulation import config
from simulation.metrics import SimulationMetrics


class Simulator:
    """Generate vehicles asynchronously; stop never joins from a UI callback.

    ``event_queue`` must be the same queue passed to ParkingLot. Stopping only
    stops future arrivals; it deliberately does not close the lot or cancel
    vehicles already admitted. The caller owns ParkingLot shutdown.
    """

    def __init__(self, parking, event_queue: Queue | None = None) -> None:
        self.parking = parking
        self.event_queue = event_queue
        self.metrics = SimulationMetrics()
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._next_vehicle_id = 1

    def start(self) -> bool:
        """Start generation on a worker thread; return promptly if already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._publish(SIMULATION_STARTED)
            self._thread = Thread(target=self._run, name="parking-simulator", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        """Request a prompt stop without blocking the caller."""
        self._stop_event.set()

    def _publish(self, event_type: str) -> None:
        if self.event_queue is not None:
            self.event_queue.put(ParkingEvent(type=event_type, timestamp=time()))

    def _run(self) -> None:
        try:
            for index in range(config.TOTAL_VEHICLES):
                if self._stop_event.is_set():
                    break
                vehicle_id = self._next_vehicle_id
                self._next_vehicle_id += 1
                duration = random.uniform(config.MIN_PARKING_TIME, config.MAX_PARKING_TIME)
                vehicle = Vehicle(vehicle_id, self.parking, duration)
                self.metrics.record_created()
                accepted = self.parking.admit(vehicle)
                self.metrics.record_admission(accepted, self.parking.snapshot())
                if not accepted:
                    break
                if index + 1 < config.TOTAL_VEHICLES and self._stop_event.wait(
                    random.uniform(config.MIN_ARRIVAL_TIME, config.MAX_ARRIVAL_TIME)
                ):
                    break
        finally:
            self._publish(SIMULATION_FINISHED)
