"""Task-oriented admission and deadline workers for an authorized parking lot."""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass
from queue import Queue
from threading import Condition, Lock, Semaphore, Thread, current_thread
from time import monotonic, time
from typing import TYPE_CHECKING

from core import events

if TYPE_CHECKING:
    from core.vehicle import Vehicle
    from simulation.authorizations import AuthorizationRegistry


@dataclass(frozen=True)
class ParkingSnapshot:
    capacity: int
    occupied_count: int
    waiting_count: int
    occupied_spaces: tuple[tuple[int, int], ...]
    active_requests: tuple[ActiveRequestSnapshot, ...] = ()


@dataclass(frozen=True)
class ActiveRequestSnapshot:
    vehicle_id: int
    plate: str
    authorized_space_id: int
    state: str
    space_id: int | None = None


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    reason: str | None
    vehicle_id: int | None
    request: Vehicle | None


class ParkingLot:
    def __init__(self, capacity: int, event_queue: Queue,
                 authorization_registry: AuthorizationRegistry) -> None:
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("Parking capacity must be positive")
        self.capacity = capacity
        self._event_queue = event_queue
        self._registry = authorization_registry
        self._condition = Condition(Lock())
        self._semaphore = Semaphore(capacity)
        self._occupied: dict[int, Vehicle] = {}
        self._pending: list[tuple[int, Vehicle, int, float]] = []
        self._deadlines: list[tuple[float, int, Vehicle, int]] = []
        self._active_plates: set[str] = set()
        self._active: dict[int, Vehicle] = {}
        self._seen_vehicle_ids: set[int] = set()
        self._sequence = 0
        self._entry_sequence = 0
        self._closed = False
        self._cancel_pending = True
        self._started = False
        self._admission_started = False
        self._departure_started = False
        self._drained = False
        self._failure: BaseException | None = None
        self._outbox: deque[object] = deque()
        self._publish_lock = Lock()
        self._admission_thread = Thread(target=self._admission_worker, name="parking-admission")
        self._departure_thread = Thread(target=self._departure_worker, name="parking-departures")

    def start(self) -> None:
        with self._condition:
            if self._started or self._closed:
                raise RuntimeError("Parking lot cannot be started")
            self._started = True
        try:
            self._admission_thread.start()
            self._admission_started = True
            self._departure_thread.start()
            self._departure_started = True
        except BaseException:
            self.close(wait=True)
            raise

    def admit(self, vehicle: Vehicle) -> AdmissionResult:
        from core.vehicle import Vehicle
        try:
            valid = (isinstance(vehicle, Vehicle) and vehicle.parking is self
                     and type(vehicle.vehicle_id) is int and vehicle.vehicle_id > 0
                     and isinstance(vehicle.plate, str)
                     and _valid_duration(getattr(vehicle, "parking_duration", None)))
        except BaseException:
            valid = False
        if not valid:
            vehicle_id = _safe_attr(vehicle, "vehicle_id", int)
            plate = _safe_attr(vehicle, "plate", str)
            self._queue_rejection(vehicle_id, _normalized_plate(plate), None, "INVALID_REQUEST")
            return AdmissionResult(False, "INVALID_REQUEST", vehicle_id, None)
        with self._condition:
            reason = None
            authorization = self._registry.lookup(vehicle.plate)
            if vehicle.vehicle_id in self._seen_vehicle_ids:
                reason = "INVALID_REQUEST"
            elif self._closed:
                reason = "LOT_CLOSED"
            elif authorization is None:
                reason = "UNKNOWN_PLATE"
            elif not authorization.authorized:
                reason = "NOT_AUTHORIZED"
            elif authorization.plate in self._active_plates:
                reason = "DUPLICATE_ACTIVE"
            elif not self._started:
                reason = "INVALID_REQUEST"
            if reason:
                plate = authorization.plate if authorization is not None else _normalized_plate(vehicle.plate)
                slot = authorization.space_id if authorization is not None and authorization.authorized else None
                rejection = (vehicle.vehicle_id, vehicle, plate, slot, reason)
            else:
                rejection = None
            if rejection is not None:
                result = AdmissionResult(False, reason, vehicle.vehicle_id, vehicle)
            else:
                result = None
            if rejection is not None:
                # Append under the state lock; publication is always outside it.
                self._queue_rejected_locked(*rejection)
            else:
                self._sequence += 1
                sequence = self._sequence
                vehicle.plate = authorization.plate
                self._active_plates.add(authorization.plate)
                self._active[vehicle.vehicle_id] = vehicle
                self._seen_vehicle_ids.add(vehicle.vehicle_id)
                self._pending.append((sequence, vehicle, authorization.space_id, monotonic()))
                self._queue_event(events.VEHICLE_CREATED, vehicle, authorized_space_id=authorization.space_id)
                self._condition.notify_all()
        self._flush_events()
        return result if result is not None else AdmissionResult(True, None, vehicle.vehicle_id, vehicle)
    def snapshot(self) -> ParkingSnapshot:
        with self._condition:
            spaces = tuple(sorted((space, vehicle.vehicle_id) for space, vehicle in self._occupied.items()))
            parked = tuple(ActiveRequestSnapshot(v.vehicle_id, v.plate, slot, "PARKED", slot)
                           for slot, v in sorted(self._occupied.items()))
            waiting = tuple(ActiveRequestSnapshot(v.vehicle_id, v.plate, slot, "WAITING")
                            for _, v, slot, _ in self._pending)
            return ParkingSnapshot(self.capacity, len(spaces), len(self._pending), spaces, parked + waiting)

    def _queue_event(self, kind: str, vehicle: Vehicle, space_id=None, waiting_time=None,
                     authorized_space_id=None, reason=None) -> None:
        if authorized_space_id is None:
            auth = self._registry.lookup(_normalized_plate(_safe_attr(vehicle, "plate", str)))
            authorized_space_id = auth.space_id if auth and auth.authorized else None
        self._outbox.append(events.ParkingEvent(kind, time(), vehicle.vehicle_id, space_id, waiting_time,
                                               _normalized_plate(vehicle.plate), authorized_space_id, reason))

    def _queue_rejection(self, vehicle_id, plate, slot, reason):
        with self._condition:
            self._queue_rejected_locked(vehicle_id, None, plate, slot, reason)
        self._flush_events()

    def _queue_rejected_locked(self, vehicle_id, vehicle, plate, slot, reason):
        self._outbox.append(events.ParkingEvent(events.VEHICLE_REJECTED, time(), vehicle_id,
                                               None, None, plate, slot, reason))

    def _flush_events(self) -> None:
        with self._publish_lock:
            while True:
                with self._condition:
                    if not self._outbox:
                        return
                    item = self._outbox.popleft()
                try:
                    self._event_queue.put(item)
                except BaseException as error:
                    with self._condition:
                        self._failure = error
                        self._closed = True
                        self._cancel_pending = True
                        self._condition.notify_all()
                    raise

    def _admission_worker(self) -> None:
        try:
            while True:
                with self._condition:
                    # Every wait is paired with its predicate check while the
                    # same Condition lock is held. A departure notification
                    # cannot slip between the no-work check and wait().
                    while True:
                        if self._failure is not None:
                            self._closed = True
                            self._cancel_pending = True
                        if self._closed and self._cancel_pending and self._pending:
                            break
                        if self._closed and not self._pending and not self._active:
                            return
                        selected = self._eligible_request_locked()
                        if selected is not None:
                            break
                        self._condition.wait()

                    if self._closed and self._cancel_pending and self._pending:
                        for _, vehicle, _, _ in self._pending:
                            vehicle._state = "CANCELLED"
                            self._queue_event(events.VEHICLE_CANCELLED, vehicle, reason="STOP_REQUESTED")
                            self._active.pop(vehicle.vehicle_id, None)
                            self._active_plates.discard(vehicle.plate)
                        self._pending.clear()
                        self._condition.notify_all()
                    else:
                        _, vehicle, slot, requested_at = selected
                        if not self._semaphore.acquire(blocking=False):
                            # A permit can only be unavailable when an
                            # occupied space exists; wait for its departure.
                            self._condition.wait()
                            continue
                        self._pending.remove(selected)
                        self._occupied[slot] = vehicle
                        vehicle._state = "PARKED"
                        self._entry_sequence += 1
                        deadline = monotonic() + float(vehicle.parking_duration)
                        heapq.heappush(self._deadlines, (deadline, self._entry_sequence, vehicle, slot))
                        self._queue_event(events.VEHICLE_ENTERED, vehicle, slot,
                                          (deadline - float(vehicle.parking_duration)) - requested_at)
                        self._condition.notify_all()
                    self._check_drained_locked()
                try:
                    self._flush_events()
                except BaseException:
                    # Publication failure closes admission, but workers still
                    # have to cancel queued requests and drain occupied ones.
                    pass
        finally:
            try:
                self._flush_events()
            except BaseException:
                pass

    def _eligible_request_locked(self):
        """Return the first pending request eligible for its authorized slot."""
        for index, entry in enumerate(self._pending):
            _, _, slot, _ = entry
            if slot in self._occupied:
                continue
            if any(earlier[2] == slot for earlier in self._pending[:index]):
                continue
            return entry
        if self._pending:
            for _, vehicle, slot, _ in self._pending:
                if vehicle._state == "CREATED":
                    vehicle._state = "WAITING"
                    self._queue_event(events.VEHICLE_WAITING, vehicle, authorized_space_id=slot)
        return None

    def _departure_worker(self) -> None:
        try:
            while True:
                with self._condition:
                    if self._deadlines:
                        delay = self._deadlines[0][0] - monotonic()
                        if delay > 0:
                            self._condition.wait(delay)
                            continue
                        _, _, vehicle, slot = heapq.heappop(self._deadlines)
                        if self._occupied.get(slot) is vehicle:
                            del self._occupied[slot]
                            self._semaphore.release()
                            self._queue_event(events.VEHICLE_EXITED, vehicle, slot)
                            vehicle._state = "FINISHED"
                            self._queue_event(events.VEHICLE_FINISHED, vehicle)
                            self._active.pop(vehicle.vehicle_id, None)
                            self._active_plates.discard(vehicle.plate)
                            self._condition.notify_all()
                    elif self._closed and not self._active:
                        self._drained = True
                        self._condition.notify_all()
                        return
                    else:
                        self._condition.wait()
                    self._check_drained_locked()
                try:
                    self._flush_events()
                except BaseException:
                    pass
        finally:
            try:
                self._flush_events()
            except BaseException:
                pass

    def _check_drained_locked(self) -> None:
        if self._closed and not self._pending and not self._active:
            self._condition.notify_all()

    def _vehicle_state(self, vehicle: Vehicle) -> str:
        with self._condition:
            return vehicle._state

    def close(self, wait: bool = True, cancel_pending: bool = True) -> None:
        if wait and current_thread() in (self._admission_thread, self._departure_thread):
            raise RuntimeError("A parking worker cannot join its parking lot")
        with self._condition:
            self._closed = True
            self._cancel_pending = self._cancel_pending and cancel_pending
            self._condition.notify_all()
            started = self._started
        try:
            self._flush_events()
        except BaseException:
            # Still join workers and establish whether state drained; surface
            # the stored publication failure after cleanup below.
            pass
        if not started or not (self._admission_started or self._departure_started):
            with self._condition:
                self._pending.clear()
                self._drained = True
            return
        if wait:
            if self._admission_started:
                self._admission_thread.join()
            if self._departure_started:
                self._departure_thread.join()
            with self._condition:
                if self._failure is not None:
                    raise RuntimeError("Parking event publication failed") from self._failure
                if self._active or self._pending:
                    raise RuntimeError("Parking lot did not drain")
                self._drained = True


def _valid_duration(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except (OverflowError, TypeError, ValueError):
        return False


def _safe_attr(value, name, expected):
    try:
        result = getattr(value, name, None)
        return result if isinstance(result, expected) and not (expected is int and type(result) is not int) else None
    except BaseException:
        return None


def _normalized_plate(value):
    if not isinstance(value, str):
        return None
    try:
        return value.strip().upper()
    except BaseException:
        return None
