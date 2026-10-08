"""Vehicle lifecycle, ordered events, and bounded shutdown races."""

from queue import Queue
from threading import Event, Thread, current_thread
from time import monotonic, sleep

import pytest

from core import events
from core.parking import ParkingLot
from core.vehicle import Vehicle


def wait_for_waiter(lot: ParkingLot) -> None:
    deadline = monotonic() + 2
    while lot.snapshot().waiting_count != 1:
        if monotonic() >= deadline:
            pytest.fail("Vehicle never entered WAITING")
        sleep(0.002)


def test_immediate_entry_publishes_normal_event_fields_and_order() -> None:
    queue = Queue()
    lot = ParkingLot(1, queue)
    vehicle = Vehicle(4, lot, 0.02)
    assert lot.admit(vehicle)
    vehicle.join(timeout=2)
    assert not vehicle.is_alive()
    assert vehicle.state == "FINISHED"

    history = list(queue.queue)
    assert [item.type for item in history] == [
        events.VEHICLE_CREATED, events.VEHICLE_ENTERED,
        events.VEHICLE_EXITED, events.VEHICLE_FINISHED,
    ]
    assert all(item.vehicle_id == 4 for item in history)
    assert history[1].space_id == history[2].space_id == 0
    assert history[1].waiting_time is not None
    assert history[1].waiting_time >= 0
    for item in (history[0], history[2], history[3]):
        assert item.waiting_time is None
    for item in (history[0], history[3]):
        assert item.space_id is None


def test_waiting_entry_only_entered_carries_waiting_time() -> None:
    queue = Queue()
    lot = ParkingLot(1, queue)
    first = Vehicle(1, lot, 0.14)
    second = Vehicle(2, lot, 0.01)
    try:
        assert lot.admit(first)
        deadline = monotonic() + 2
        while lot.snapshot().occupied_count != 1:
            assert monotonic() < deadline
            sleep(0.002)
        assert lot.admit(second)
        wait_for_waiter(lot)
    finally:
        for vehicle in (first, second):
            if vehicle.ident is not None:
                vehicle.join(timeout=2)
                assert not vehicle.is_alive()

    history = [item for item in list(queue.queue) if item.vehicle_id == 2]
    assert [item.type for item in history] == [
        events.VEHICLE_CREATED, events.VEHICLE_WAITING, events.VEHICLE_ENTERED,
        events.VEHICLE_EXITED, events.VEHICLE_FINISHED,
    ]
    assert history[2].space_id == history[3].space_id
    assert history[2].waiting_time is not None
    assert history[2].waiting_time >= 0
    assert all(item.waiting_time is None for item in history if item.type != events.VEHICLE_ENTERED)
    assert all(item.space_id is None for item in (history[0], history[1], history[4]))


def test_close_cancels_waiters_but_lets_parked_vehicle_finish() -> None:
    queue = Queue()
    lot = ParkingLot(1, queue)
    parked = Vehicle(1, lot, 0.25)
    waiter = Vehicle(2, lot, 0.01)
    try:
        assert lot.admit(parked)
        wait_for_parked(lot)
        assert lot.admit(waiter)
        wait_for_waiter(lot)
        lot.close(wait=False)
        lot.close(wait=False)
        rejected = Vehicle(3, lot, 0.01)
        assert lot.admit(rejected) is False
        assert rejected.ident is None
        waiter.join(timeout=2)
        assert not waiter.is_alive()
        assert parked.is_alive()
        assert lot.snapshot().occupied_spaces == ((0, 1),)
        lot.close(wait=True)
        assert not parked.is_alive()
    finally:
        lot.close(wait=False)
        for vehicle in (parked, waiter):
            if vehicle.ident is not None:
                vehicle.join(timeout=2)

    history = list(queue.queue)
    assert [event.type for event in history if event.vehicle_id == 2] == [
        events.VEHICLE_CREATED, events.VEHICLE_WAITING, events.VEHICLE_FINISHED,
    ]
    assert [event.type for event in history if event.vehicle_id == 1] == [
        events.VEHICLE_CREATED, events.VEHICLE_ENTERED,
        events.VEHICLE_EXITED, events.VEHICLE_FINISHED,
    ]
    assert {event.type for event in history} <= {
        events.VEHICLE_CREATED, events.VEHICLE_WAITING, events.VEHICLE_ENTERED,
        events.VEHICLE_EXITED, events.VEHICLE_FINISHED,
    }
    assert all(event.waiting_time is None for event in history
               if event.type != events.VEHICLE_ENTERED)
    assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0
    assert lot._semaphore._value == lot.capacity


def wait_for_parked(lot: ParkingLot) -> None:
    deadline = monotonic() + 2
    while lot.snapshot().occupied_count != 1:
        if monotonic() >= deadline:
            pytest.fail("Vehicle never entered PARKED")
        sleep(0.002)


def test_close_after_waiter_acquires_before_commit_drains_credits_at_end(monkeypatch) -> None:
    queue = Queue()
    lot = ParkingLot(1, queue)
    parked = Vehicle(1, lot, 0.08)
    waiter = Vehicle(2, lot, 0.01)
    acquired = Event()
    resume = Event()
    original_acquire = lot._semaphore.acquire

    def paused_acquire(*args, **kwargs):
        result = original_acquire(*args, **kwargs)
        if current_thread() is waiter and result and kwargs.get("blocking", True):
            acquired.set()
            assert resume.wait(timeout=2)
        return result

    monkeypatch.setattr(lot._semaphore, "acquire", paused_acquire)
    try:
        assert lot.admit(parked)
        wait_for_parked(lot)
        assert lot.admit(waiter)
        wait_for_waiter(lot)
        # The parked vehicle releases its real permit into the blocked acquire.
        assert acquired.wait(timeout=2)
        lot.close(wait=False)
        assert lot._wake_credits == 1
        assert [event.type for event in queue.queue if event.vehicle_id == 2] == [
            events.VEHICLE_CREATED, events.VEHICLE_WAITING,
        ]
        resume.set()
        waiter.join(timeout=2)
        assert not waiter.is_alive()
        lot.close(wait=True)
    finally:
        resume.set()
        lot.close(wait=False)
        for vehicle in (parked, waiter):
            if vehicle.ident is not None:
                vehicle.join(timeout=2)

    assert [event.type for event in queue.queue if event.vehicle_id == 2] == [
        events.VEHICLE_CREATED, events.VEHICLE_WAITING, events.VEHICLE_FINISHED,
    ]
    assert lot._wake_credits == 0
    assert lot._semaphore._value == lot.capacity


def test_created_worker_closes_without_parking_and_join_waits_for_thread_return() -> None:
    queue = Queue()
    lot = ParkingLot(1, queue)
    started = Event()
    proceed = Event()

    class DelayedVehicle(Vehicle):
        def run(self) -> None:
            started.set()
            assert proceed.wait(timeout=2)
            super().run()

    vehicle = DelayedVehicle(1, lot, 0.01)
    closer = Thread(target=lambda: lot.close(wait=True))
    try:
        assert lot.admit(vehicle)
        assert started.wait(timeout=2)
        closer.start()
        closer.join(timeout=0.02)
        assert closer.is_alive()
        assert lot.snapshot().waiting_count == 0
        proceed.set()
        closer.join(timeout=2)
        assert not closer.is_alive()
        assert not vehicle.is_alive()
    finally:
        proceed.set()
        lot.close(wait=False)
        if vehicle.ident is not None:
            vehicle.join(timeout=2)
        if closer.ident is not None:
            closer.join(timeout=2)
    assert [event.type for event in queue.queue] == [
        events.VEHICLE_CREATED, events.VEHICLE_FINISHED,
    ]
    assert lot._semaphore._value == lot.capacity


def test_self_join_rejected_before_changing_close_state() -> None:
    queue = Queue()
    lot = ParkingLot(1, queue)
    outcome = Queue()

    class ClosingVehicle(Vehicle):
        def run(self) -> None:
            try:
                self.parking.close(wait=True)
            except RuntimeError as error:
                outcome.put(error)
            super().run()

    vehicle = ClosingVehicle(1, lot, 0.01)
    try:
        assert lot.admit(vehicle)
        vehicle.join(timeout=2)
        assert not vehicle.is_alive()
        assert isinstance(outcome.get(timeout=1), RuntimeError)
        assert lot.admit(Vehicle(2, lot, 0.01)) is True
    finally:
        lot.close(wait=True)
    assert lot._semaphore._value == lot.capacity


def test_close_waits_for_finished_publication_and_thread_return() -> None:
    lot = ParkingLot(1, Queue())
    published = Event()
    proceed = Event()
    original_exit = lot._exit

    def delayed_exit(vehicle, space_id):
        original_exit(vehicle, space_id)
        published.set()
        assert proceed.wait(timeout=2)

    lot._exit = delayed_exit
    vehicle = Vehicle(1, lot, 0.01)
    closer = Thread(target=lambda: lot.close(wait=True))
    try:
        assert lot.admit(vehicle)
        assert published.wait(timeout=2)
        closer.start()
        closer.join(timeout=0.02)
        assert closer.is_alive()
        proceed.set()
        closer.join(timeout=2)
        assert not closer.is_alive()
        assert not vehicle.is_alive()
    finally:
        proceed.set()
        lot.close(wait=False)
        if vehicle.ident is not None:
            vehicle.join(timeout=2)
        if closer.ident is not None:
            closer.join(timeout=2)


def test_repeated_contention_shutdown_has_single_pass_events_and_no_leaked_credits() -> None:
    for _ in range(12):
        queue = Queue()
        lot = ParkingLot(1, queue)
        vehicles = [Vehicle(index, lot, 0.08) for index in range(5)]
        try:
            assert lot.admit(vehicles[0])
            wait_for_parked(lot)
            for vehicle in vehicles[1:]:
                assert lot.admit(vehicle)
            deadline = monotonic() + 2
            while lot.snapshot().waiting_count != 4:
                if monotonic() >= deadline:
                    pytest.fail("Not all waiters registered before close")
                sleep(0.002)
            lot.close(wait=False)
            lot.close(wait=False)
            for vehicle in vehicles:
                vehicle.join(timeout=2)
                assert not vehicle.is_alive()
            lot.close(wait=True)
            assert lot.snapshot().occupied_spaces == ()
            assert lot.snapshot().waiting_count == 0
            assert lot._wake_credits == 0
            assert lot._semaphore._value == lot.capacity
            for index, vehicle in enumerate(vehicles):
                assert vehicle.state == "FINISHED"
                history = [event.type for event in queue.queue if event.vehicle_id == index]
                if index == 0:
                    assert history == [
                        events.VEHICLE_CREATED, events.VEHICLE_ENTERED,
                        events.VEHICLE_EXITED, events.VEHICLE_FINISHED,
                    ]
                else:
                    assert history == [
                        events.VEHICLE_CREATED, events.VEHICLE_WAITING,
                        events.VEHICLE_FINISHED,
                    ]
        finally:
            lot.close(wait=False)
            for vehicle in vehicles:
                if vehicle.ident is not None:
                    vehicle.join(timeout=2)
