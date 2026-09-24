"""Focused admission, capacity, and snapshot tests for the core lot."""

from dataclasses import FrozenInstanceError
from queue import Queue
from threading import Event
from time import monotonic, sleep

import pytest

from core import events
from core.parking import ParkingLot
from core.vehicle import Vehicle


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        if monotonic() >= deadline:
            pytest.fail("Timed out waiting for vehicle transition")
        sleep(0.002)


def join_vehicles(*vehicles: Vehicle) -> None:
    for vehicle in vehicles:
        if vehicle.ident is not None:
            vehicle.join(timeout=2)
            assert not vehicle.is_alive()


def test_constructor_and_admission_guards() -> None:
    for capacity in (0, -1):
        with pytest.raises(ValueError):
            ParkingLot(capacity, Queue())

    queue = Queue()
    lot = ParkingLot(1, queue)
    other = ParkingLot(1, Queue())
    vehicle = Vehicle(1, lot, 0.03)
    with pytest.raises(ValueError):
        other.admit(vehicle)
    try:
        assert lot.admit(vehicle) is True
        with pytest.raises((ValueError, RuntimeError)):
            lot.admit(vehicle)
    finally:
        join_vehicles(vehicle)
    assert [item.type for item in queue.queue].count(events.VEHICLE_CREATED) == 1

    lot.close()
    rejected = Vehicle(2, lot, 0.01)
    assert lot.admit(rejected) is False
    assert rejected.ident is None


def test_failed_thread_start_rolls_back_without_created_event() -> None:
    class UnstartableVehicle(Vehicle):
        def start(self) -> None:
            raise RuntimeError("start failed")

    queue = Queue()
    lot = ParkingLot(1, queue)
    vehicle = UnstartableVehicle(1, lot, 0.01)
    with pytest.raises(RuntimeError, match="start failed"):
        lot.admit(vehicle)
    assert lot.snapshot().occupied_count == 0
    assert lot.snapshot().waiting_count == 0
    assert queue.empty()


def test_created_worker_is_not_counted_as_waiting() -> None:
    started = Event()
    proceed = Event()

    class DelayedVehicle(Vehicle):
        def run(self) -> None:
            started.set()
            assert proceed.wait(timeout=2)
            super().run()

    lot = ParkingLot(1, Queue())
    vehicle = DelayedVehicle(1, lot, 0.02)
    try:
        assert lot.admit(vehicle)
        assert started.wait(timeout=2)
        assert lot.snapshot().waiting_count == 0
        assert lot.snapshot().occupied_count == 0
    finally:
        proceed.set()
        join_vehicles(vehicle)


def test_full_lot_admission_is_nonblocking_and_reuses_exclusive_space() -> None:
    lot = ParkingLot(1, Queue())
    first = Vehicle(1, lot, 0.18)
    second = Vehicle(2, lot, 0.08)
    try:
        assert lot.admit(first)
        wait_until(lambda: lot.snapshot().occupied_count == 1)
        start = monotonic()
        assert lot.admit(second)
        assert monotonic() - start < 0.1
        wait_until(lambda: lot.snapshot().waiting_count == 1)
        parked = lot.snapshot()
        assert parked.occupied_spaces == ((0, 1),)
        assert second.state == "WAITING"
        wait_until(lambda: lot.snapshot().occupied_spaces == ((0, 2),))
        assert first.state == "FINISHED"
    finally:
        join_vehicles(first, second)
    assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0


def test_snapshots_are_frozen_sorted_copies_under_load() -> None:
    release_parked = Event()

    class BlockingVehicle(Vehicle):
        def run(self) -> None:
            space_id = self.parking._enter(self)
            if space_id is None:
                return
            try:
                release_parked.wait(timeout=2)
            finally:
                self.parking._exit(self, space_id)

    lot = ParkingLot(2, Queue())
    empty = lot.snapshot()
    assert (empty.capacity, empty.occupied_count, empty.waiting_count, empty.occupied_spaces) == (
        2, 0, 0, (),
    )
    with pytest.raises(FrozenInstanceError):
        empty.occupied_count = 1

    vehicles = [BlockingVehicle(index, lot, 0.12) for index in range(8)]
    try:
        for vehicle in vehicles:
            assert lot.admit(vehicle)
        wait_until(lambda: (
            lot.snapshot().occupied_count == 2
            and lot.snapshot().waiting_count >= 1
        ))
        snapshot = lot.snapshot()
        assert snapshot.occupied_count == 2
        assert snapshot.waiting_count == sum(v.state == "WAITING" for v in vehicles)
        for _ in range(150):
            current = lot.snapshot()
            spaces = current.occupied_spaces
            assert current.occupied_count == len(spaces) <= current.capacity
            assert len({space for space, _ in spaces}) == len(spaces)
            assert spaces == tuple(sorted(spaces))
            assert 0 <= current.waiting_count <= len(vehicles)
            sleep(0.002)
    finally:
        release_parked.set()
        join_vehicles(*vehicles)
    assert empty.occupied_spaces == ()
    assert snapshot.occupied_count == 2
    assert lot.snapshot().occupied_spaces == ()
