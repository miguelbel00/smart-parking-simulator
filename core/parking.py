"""Semaphore-gated parking spaces and lock-consistent vehicle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Lock, Semaphore, current_thread
from time import monotonic, time
from typing import TYPE_CHECKING

from core import events

if TYPE_CHECKING:
    from core.vehicle import Vehicle


@dataclass(frozen=True)
class ParkingSnapshot:
    capacity: int
    occupied_count: int
    waiting_count: int
    occupied_spaces: tuple[tuple[int, int], ...]


class ParkingLot:
    """Owns capacity, space IDs, state transitions, and event publication."""

    def __init__(self, capacity: int, event_queue: Queue) -> None:
        if capacity <= 0:
            raise ValueError("Parking capacity must be positive")
        self.capacity = capacity
        self._event_queue = event_queue
        self._lock = Lock()
        self._semaphore = Semaphore(capacity)
        self._occupied: dict[int, int] = {}
        self._waiting: set[Vehicle] = set()
        self._active: set[Vehicle] = set()
        self._threads: list[Vehicle] = []
        self._closed = False
        self._wake_credits = 0

    def _publish(self, event_type: str, vehicle: Vehicle,
                 space_id: int | None = None,
                 waiting_time: float | None = None) -> None:
        self._event_queue.put(events.ParkingEvent(
            type=event_type,
            timestamp=time(),
            vehicle_id=vehicle.vehicle_id,
            space_id=space_id,
            waiting_time=waiting_time,
        ))

    def admit(self, vehicle: Vehicle) -> bool:
        from core.vehicle import Vehicle

        with self._lock:
            if self._closed:
                return False
            if not isinstance(vehicle, Vehicle) or vehicle.parking is not self:
                raise ValueError("Vehicle belongs to another parking lot")
            if vehicle in self._active or vehicle.ident is not None or vehicle in self._threads:
                raise ValueError("Vehicle has already been admitted")
            self._active.add(vehicle)
            try:
                # Starting under the lock keeps CREATED ahead of worker transitions.
                vehicle.start()
            except BaseException:
                self._active.remove(vehicle)
                raise
            self._threads.append(vehicle)
            self._publish(events.VEHICLE_CREATED, vehicle)
            return True

    def snapshot(self) -> ParkingSnapshot:
        with self._lock:
            spaces = tuple(sorted(self._occupied.items()))
            return ParkingSnapshot(
                capacity=self.capacity,
                occupied_count=len(spaces),
                waiting_count=len(self._waiting),
                occupied_spaces=spaces,
            )

    def _set_state(self, vehicle: Vehicle, state: str) -> None:
        """Only call while holding the lot lock."""
        vehicle._state = state

    def _finish(self, vehicle: Vehicle) -> None:
        """Complete a lifecycle and reconcile close credits after the last one."""
        self._set_state(vehicle, "FINISHED")
        self._publish(events.VEHICLE_FINISHED, vehicle)
        self._active.remove(vehicle)
        if self._closed and not self._active:
            for _ in range(self._wake_credits):
                assert self._semaphore.acquire(blocking=False)
            self._wake_credits = 0

    def _enter(self, vehicle: Vehicle) -> int | None:
        """Acquire capacity in the worker, never in the admission caller."""
        waiting_since = monotonic()
        with self._lock:
            if self._closed:
                self._finish(vehicle)
                return None
            if self._semaphore.acquire(blocking=False):
                acquired = True
            else:
                acquired = False
                self._waiting.add(vehicle)
                self._set_state(vehicle, "WAITING")
                self._publish(events.VEHICLE_WAITING, vehicle)

        if not acquired:
            self._semaphore.acquire()

        with self._lock:
            self._waiting.discard(vehicle)
            if self._closed:
                self._semaphore.release()
                self._finish(vehicle)
                return None
            space_id = next(space for space in range(self.capacity)
                            if space not in self._occupied)
            self._occupied[space_id] = vehicle.vehicle_id
            self._set_state(vehicle, "PARKED")
            self._publish(events.VEHICLE_ENTERED, vehicle, space_id,
                          monotonic() - waiting_since)
            return space_id

    def _exit(self, vehicle: Vehicle, space_id: int) -> None:
        with self._lock:
            del self._occupied[space_id]
            self._publish(events.VEHICLE_EXITED, vehicle, space_id)
            self._semaphore.release()
            self._finish(vehicle)

    def _vehicle_state(self, vehicle: Vehicle) -> str:
        with self._lock:
            return vehicle._state

    def close(self, wait: bool = True) -> None:
        """Reject admissions, wake waiters once, and optionally join all workers."""
        with self._lock:
            if wait and current_thread() in self._threads:
                raise RuntimeError("A vehicle cannot join its own parking lot")
            if not self._closed:
                self._closed = True
                self._wake_credits = len(self._waiting)
                for _ in range(self._wake_credits):
                    self._semaphore.release()
            threads = tuple(self._threads) if wait else ()

        for vehicle in threads:
            vehicle.join()
