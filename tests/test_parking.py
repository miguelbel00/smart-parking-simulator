from queue import Queue
import math
from threading import Event, Thread, current_thread, enumerate as active_threads
from time import monotonic, sleep

import pytest

from core.events import (VEHICLE_CANCELLED, VEHICLE_CREATED, VEHICLE_ENTERED,
                         VEHICLE_EXITED, VEHICLE_FINISHED, VEHICLE_REJECTED)
from core.parking import ParkingLot
from core.vehicle import Vehicle
from simulation.authorizations import Authorization, AuthorizationRegistry


def registry(*records):
    return AuthorizationRegistry({plate: Authorization(plate, allowed, slot)
                                  for plate, allowed, slot in records})


def make_lot(capacity=2, records=None, queue=None):
    records = records or [(f"P{i}", True, i % capacity) for i in range(8)]
    return ParkingLot(capacity, queue or Queue(), registry(*records))


def until(predicate, timeout=2):
    limit = monotonic() + timeout
    while not predicate():
        assert monotonic() < limit
        sleep(.002)


def request(lot, vehicle_id, plate, duration=.03):
    return Vehicle(vehicle_id, lot, duration, plate)


def test_fixed_workers_capacity_exact_slot_and_lifecycle_order():
    q = Queue()
    lot = make_lot(2, [("A", True, 1), ("B", True, 0)], q)
    lot.start()
    a = request(lot, 1, "A", .04)
    b = request(lot, 2, "B", .04)
    assert lot.admit(a).accepted and lot.admit(b).accepted
    until(lambda: lot.snapshot().occupied_count == 2)
    assert lot.snapshot().occupied_spaces == ((0, 2), (1, 1))
    assert {lot._admission_thread, lot._departure_thread} <= set(active_threads())
    lot.close(cancel_pending=False)
    assert lot._semaphore._value == 2
    kinds = [event.type for event in q.queue if event.vehicle_id == 1]
    assert kinds == [VEHICLE_CREATED, VEHICLE_ENTERED, VEHICLE_EXITED, VEHICLE_FINISHED]


def test_rejection_reasons_and_duplicate_active_for_waiting_and_parked():
    lot = make_lot(1, [("A", True, 0), ("B", True, 0), ("NO", False, None)])
    lot.start()
    assert lot.admit(request(lot, 1, "missing")).reason == "UNKNOWN_PLATE"
    assert lot.admit(request(lot, 2, "NO")).reason == "NOT_AUTHORIZED"
    assert lot.admit(request(lot, 3, "A", .2)).accepted
    until(lambda: lot.snapshot().occupied_count == 1)
    assert lot.admit(request(lot, 4, "A")).reason == "DUPLICATE_ACTIVE"
    assert lot.admit(request(lot, 5, "B")).accepted
    assert lot.admit(request(lot, 6, "B")).reason == "DUPLICATE_ACTIVE"
    lot.close(wait=False)
    assert lot.admit(request(lot, 7, "A")).reason == "LOT_CLOSED"
    lot.close()
    assert lot.snapshot().waiting_count == lot.snapshot().occupied_count == 0
    invalid = Vehicle(8, lot, -1, "A")
    # Invalid requests are rejected before closed-lot lookup.
    assert lot.admit(invalid).reason == "INVALID_REQUEST"


def test_waiting_events_and_immutable_snapshot_carry_authorized_slot():
    from dataclasses import FrozenInstanceError

    q = Queue()
    lot = make_lot(2, [("A", True, 0), ("B", True, 0)], q)
    lot.start()
    occupied = request(lot, 1, "A", .15)
    waiting = request(lot, 2, "B", .01)
    assert lot.admit(occupied).accepted and lot.admit(waiting).accepted
    until(lambda: lot.snapshot().waiting_count == 1)
    snapshot = lot.snapshot()
    waiting_view = next(item for item in snapshot.active_requests if item.vehicle_id == 2)
    assert (waiting_view.plate, waiting_view.authorized_space_id,
            waiting_view.state, waiting_view.space_id) == ("B", 0, "WAITING", None)
    with pytest.raises(FrozenInstanceError):
        waiting_view.state = "PARKED"
    waiting_event = next(item for item in q.queue
                         if item.type == "VEHICLE_WAITING" and item.vehicle_id == 2)
    created = next(item for item in q.queue
                   if item.type == VEHICLE_CREATED and item.vehicle_id == 2)
    assert (waiting_event.space_id, waiting_event.authorized_space_id, waiting_event.plate) == (None, 0, "B")
    assert (created.space_id, created.authorized_space_id, created.plate) == (None, 0, "B")
    lot.close()


def test_same_slot_fifo_and_progress_on_other_slot():
    queue = Queue()
    lot = make_lot(2, [("A1", True, 0), ("A2", True, 0), ("B", True, 1)], queue)
    lot.start()
    a1 = request(lot, 1, "A1", .08)
    a2 = request(lot, 2, "A2", .01)
    b = request(lot, 3, "B", .01)
    assert all(lot.admit(v).accepted for v in (a1, a2, b))
    until(lambda: lot.snapshot().occupied_count == 2)
    assert lot.snapshot().occupied_spaces == ((0, 1), (1, 3))
    lot.close(cancel_pending=False)
    assert a2.state == "FINISHED" and b.state == "FINISHED"
    entries = [event.vehicle_id for event in list(queue.queue)
               if event.type == "VEHICLE_ENTERED"]
    assert entries.index(1) < entries.index(2)


def test_three_same_slot_requests_enter_in_fifo_order_across_releases():
    q = Queue()
    lot = make_lot(1, [(f"P{i}", True, 0) for i in range(1, 4)], q)
    lot.start()
    vehicles = [request(lot, i, f"P{i}", .04) for i in range(1, 4)]
    try:
        assert all(lot.admit(vehicle).accepted for vehicle in vehicles)
        until(lambda: lot.snapshot().waiting_count == 2)
        lot.close(cancel_pending=False)
        events = list(q.queue)
        entered = [event.vehicle_id for event in events if event.type == VEHICLE_ENTERED]
        assert entered == [1, 2, 3]
        assert len(set(entered)) == len(entered)
        assert all(vehicle.state == "FINISHED" for vehicle in vehicles)
        assert lot.snapshot().occupied_count <= lot.capacity
    finally:
        lot.close()


def test_oldest_eligible_request_is_selected_before_later_eligible_request():
    entered_blocked = Event()
    release_entered = Event()

    class PausingEntryQueue(Queue):
        def put(self, item, *args, **kwargs):
            result = super().put(item, *args, **kwargs)
            if item.type == VEHICLE_ENTERED and item.vehicle_id == 1:
                entered_blocked.set()
                assert release_entered.wait(5)
            return result

    q = PausingEntryQueue()
    records = [("BLOCKER", True, 2), ("OLDER", True, 0), ("LATER", True, 1)]
    lot = make_lot(3, records, q)
    lot.start()
    vehicles = [request(lot, 1, "BLOCKER", .05),
                request(lot, 2, "OLDER", .01),
                request(lot, 3, "LATER", .01)]
    results = []
    threads = []

    def admit(vehicle):
        results.append(lot.admit(vehicle))

    try:
        blocker_thread = Thread(target=admit, args=(vehicles[0],))
        blocker_thread.start()
        threads.append(blocker_thread)
        assert entered_blocked.wait(2)
        until(lambda: lot.snapshot().occupied_count == 1)

        older_thread = Thread(target=admit, args=(vehicles[1],))
        older_thread.start()
        threads.append(older_thread)
        until(lambda: lot.snapshot().waiting_count == 1)

        later_thread = Thread(target=admit, args=(vehicles[2],))
        later_thread.start()
        threads.append(later_thread)
        until(lambda: lot.snapshot().waiting_count == 2)

        # Both requests are accepted and eligible for distinct free slots
        # before the admission worker resumes its selection cycle.
        snapshot = lot.snapshot()
        assert snapshot.occupied_count == 1
        assert {item.vehicle_id for item in snapshot.active_requests} == {1, 2, 3}
    finally:
        release_entered.set()
        for thread in threads:
            thread.join(2)
        lot.close(cancel_pending=False)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 3 and all(result.accepted for result in results)
    events = list(q.queue)
    entered = [event.vehicle_id for event in events if event.type == VEHICLE_ENTERED]
    assert entered == [1, 2, 3]
    terminals = [event.vehicle_id for event in events
                 if event.type in (VEHICLE_FINISHED, VEHICLE_CANCELLED)]
    assert sorted(terminals) == [1, 2, 3]
    assert len(set(terminals)) == 3
    assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0


def test_close_cancels_waiting_and_drains_committed_occupancy():
    q = Queue()
    lot = make_lot(1, [("A", True, 0), ("B", True, 0)], q)
    lot.start()
    parked, waiting = request(lot, 1, "A", .08), request(lot, 2, "B", .01)
    assert lot.admit(parked).accepted and lot.admit(waiting).accepted
    until(lambda: lot.snapshot().waiting_count == 1)
    lot.close(wait=False)
    assert lot.snapshot().occupied_count == 1
    lot.close()
    assert waiting.state == "CANCELLED" and parked.state == "FINISHED"
    waiting_events = [event for event in q.queue if event.vehicle_id == waiting.vehicle_id]
    assert [event.type for event in waiting_events] == [VEHICLE_CREATED, "VEHICLE_WAITING", VEHICLE_CANCELLED]
    assert waiting_events[-1].reason == "STOP_REQUESTED"
    assert lot._semaphore._value == 1


def test_early_close_cancels_all_pending_once_and_finishes_occupant():
    q = Queue()
    records = [(f"P{i}", True, 0) for i in range(1, 5)]
    lot = make_lot(1, records, q)
    lot.start()
    vehicles = [request(lot, i, f"P{i}", .06) for i in range(1, 5)]
    try:
        assert all(lot.admit(vehicle).accepted for vehicle in vehicles)
        until(lambda: lot.snapshot().waiting_count == 3)
        lot.close(wait=False)
        lot.close(wait=True)
        events = list(q.queue)
        terminals = [event for event in events
                     if event.type in (VEHICLE_FINISHED, VEHICLE_CANCELLED)]
        assert len(terminals) == 4
        assert len({event.vehicle_id for event in terminals}) == 4
        assert sum(event.type == VEHICLE_FINISHED for event in terminals) == 1
        assert sum(event.type == VEHICLE_CANCELLED for event in terminals) == 3
        assert all(event.reason == "STOP_REQUESTED" for event in terminals
                   if event.type == VEHICLE_CANCELLED)
        assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0
        cancelled_plates = {vehicle.plate for vehicle in vehicles[1:]}
        assert cancelled_plates.isdisjoint(lot._active_plates)
        # The lot is closed, so public admit() cannot demonstrate plate reuse;
        # this white-box invariant confirms cancellation released those plates.
    finally:
        lot.close()


def test_natural_close_drains_multiple_pending_with_one_terminal_each():
    q = Queue()
    records = [(f"P{i}", True, 0) for i in range(1, 5)]
    lot = make_lot(1, records, q)
    lot.start()
    vehicles = [request(lot, i, f"P{i}", .03) for i in range(1, 5)]
    try:
        assert all(lot.admit(vehicle).accepted for vehicle in vehicles)
        until(lambda: lot.snapshot().waiting_count == 3)
        until(lambda: any(event.type == VEHICLE_FINISHED and event.vehicle_id == 1
                          for event in list(q.queue)))
        replacement = request(lot, 5, "P1", .01)
        assert lot.admit(replacement).accepted
        lot.close(cancel_pending=False)
        terminals = [event for event in list(q.queue)
                     if event.type in (VEHICLE_FINISHED, VEHICLE_CANCELLED)]
        assert [event.vehicle_id for event in terminals] == [1, 2, 3, 4, 5]
        assert all(event.type == VEHICLE_FINISHED for event in terminals)
        assert len({event.vehicle_id for event in terminals}) == 5
        assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0
        events = list(q.queue)
        assert sum(event.type == VEHICLE_FINISHED and event.vehicle_id == 5
                   for event in events) == 1
        assert replacement.state == "FINISHED"
    finally:
        lot.close()


@pytest.mark.parametrize("natural_first", [True, False])
def test_stop_escalation_cannot_be_downgraded_by_natural_close(natural_first):
    q = Queue()
    lot = make_lot(1, [(f"P{i}", True, 0) for i in range(1, 5)], q)
    lot.start()
    vehicles = [request(lot, i, f"P{i}", .3) for i in range(1, 4)]
    try:
        assert lot.admit(vehicles[0]).accepted
        until(lambda: lot.snapshot().occupied_count == 1)
        assert all(lot.admit(vehicle).accepted for vehicle in vehicles[1:])
        if natural_first:
            lot.close(wait=False, cancel_pending=False)
        lot.close(wait=False, cancel_pending=True)
        # A producer's stale natural close must not undo the explicit Stop.
        lot.close(wait=True, cancel_pending=False)
        events = list(q.queue)
        terminals = [event for event in events
                     if event.type in (VEHICLE_FINISHED, VEHICLE_CANCELLED)]
        assert sorted((event.vehicle_id, event.type, event.reason) for event in terminals) == [
            (1, VEHICLE_FINISHED, None),
            (2, VEHICLE_CANCELLED, "STOP_REQUESTED"),
            (3, VEHICLE_CANCELLED, "STOP_REQUESTED"),
        ]
        assert [event.vehicle_id for event in events if event.type == VEHICLE_ENTERED] == [1]
        assert [event.vehicle_id for event in events if event.type == VEHICLE_EXITED] == [1]
        assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0
        before = lot.snapshot()
        rejected = lot.admit(request(lot, 4, "P4"))
        assert not rejected.accepted and rejected.reason == "LOT_CLOSED"
        assert lot.snapshot() == before
        assert q.queue[-1].type == VEHICLE_REJECTED
        assert q.queue[-1].reason == "LOT_CLOSED"
    finally:
        lot.close()


def test_repeated_natural_close_still_drains_accepted_requests():
    q = Queue()
    lot = make_lot(1, [(f"P{i}", True, 0) for i in range(1, 4)], q)
    lot.start()
    vehicles = [request(lot, i, f"P{i}", .03) for i in range(1, 4)]
    try:
        assert lot.admit(vehicles[0]).accepted
        until(lambda: lot.snapshot().occupied_count == 1)
        assert all(lot.admit(vehicle).accepted for vehicle in vehicles[1:])
        lot.close(wait=False, cancel_pending=False)
        lot.close(wait=True, cancel_pending=False)
        events = list(q.queue)
        assert not any(event.type == VEHICLE_CANCELLED for event in events)
        for kind in (VEHICLE_ENTERED, VEHICLE_EXITED, VEHICLE_FINISHED):
            assert [event.vehicle_id for event in events if event.type == kind] == [1, 2, 3]
        assert all(vehicle.state == "FINISHED" for vehicle in vehicles)
        assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0
    finally:
        lot.close()


def test_invalid_request_and_vehicle_is_not_thread():
    lot = make_lot()
    lot.start()
    vehicle = Vehicle(1, lot, 0, "P0")
    assert not isinstance(vehicle, Thread)
    vehicle.plate = 7
    assert lot.admit(vehicle).reason == "INVALID_REQUEST"
    lot.close()


@pytest.mark.parametrize("duration", [True, False, "1", None, math.nan, math.inf, -math.inf, -0.01])
def test_invalid_durations_have_no_admission_side_effects(duration):
    q = Queue()
    lot = make_lot(1, [("A", True, 0)], q)
    lot.start()
    try:
        invalid = request(lot, 1, "A", duration)
        before = lot.snapshot()
        result = lot.admit(invalid)
        assert not result.accepted and result.reason == "INVALID_REQUEST"
        assert lot.snapshot() == before
        assert lot._semaphore._value == 1
        assert not lot._active and not lot._active_plates and not lot._pending
        assert [event.type for event in q.queue] == [VEHICLE_REJECTED]

        valid = request(lot, 1, "A", 0)
        assert lot.admit(valid).accepted
        lot.close(cancel_pending=False)
        assert valid.state == "FINISHED"
    finally:
        lot.close()


def test_zero_duration_completes_lifecycle_and_close_without_waiting():
    entered = Event()

    class EntryQueue(Queue):
        def put(self, item, *args, **kwargs):
            result = super().put(item, *args, **kwargs)
            if item.type == VEHICLE_ENTERED:
                entered.set()
            return result

    q = EntryQueue()
    lot = make_lot(1, [("A", True, 0)], q)
    lot.start()
    vehicle = request(lot, 1, "A", 0)
    try:
        assert lot.admit(vehicle).accepted
        assert entered.wait(2)
        lot.close()
        assert vehicle.state == "FINISHED"
        assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0
        assert lot._semaphore._value == 1
        assert [event.type for event in list(q.queue) if event.vehicle_id == 1] == [
            VEHICLE_CREATED, VEHICLE_ENTERED, VEHICLE_EXITED, VEHICLE_FINISHED,
        ]
    finally:
        lot.close()


def test_created_publication_cannot_be_overtaken_by_worker_events():
    class BlockingQueue(Queue):
        def __init__(self):
            super().__init__()
            self.created_entered = Event()
            self.release_created = Event()

        def put(self, item, *args, **kwargs):
            if item.type == VEHICLE_CREATED:
                self.created_entered.set()
                if not self.release_created.wait(5):
                    raise AssertionError("test did not release CREATED publication")
            return super().put(item, *args, **kwargs)

    q = BlockingQueue()
    lot = make_lot(1, [("A", True, 0)], q)
    lot.start()
    vehicle = request(lot, 1, "A", .02)
    admitted = Thread(target=lot.admit, args=(vehicle,))
    try:
        admitted.start()
        assert q.created_entered.wait(2)
        # The commit appends ENTERED while CREATED's put holds _publish_lock.
        # Releasing the first put must drain the shared outbox in append order.
        until(lambda: lot.snapshot().occupied_count == 1)
    finally:
        q.release_created.set()
        admitted.join(5)
        lot.close()
    assert not admitted.is_alive()
    kinds = [event.type for event in list(q.queue) if event.vehicle_id == 1]
    assert kinds == [VEHICLE_CREATED, VEHICLE_ENTERED, VEHICLE_EXITED, VEHICLE_FINISHED]


def test_early_close_cannot_lose_final_departure_notification():
    q = Queue()
    lot = make_lot(1, [("A", True, 0)], q)
    admission_waiting = Event()
    original_wait = lot._condition.wait

    def observe_admission_wait(timeout=None):
        if current_thread() is lot._admission_thread:
            admission_waiting.set()
        return original_wait(timeout)

    lot._condition.wait = observe_admission_wait
    lot.start()
    try:
        vehicle = request(lot, 1, "A", 30)
        assert lot.admit(vehicle).accepted
        until(lambda: lot.snapshot().occupied_count == 1)
        lot.close(wait=False)
        assert admission_waiting.wait(2)
        # The admission thread announces immediately before Condition.wait,
        # while holding the condition lock. This transition cannot notify
        # until wait atomically releases that lock.
        with lot._condition:
            deadline, sequence, due_vehicle, slot = lot._deadlines[0]
            lot._deadlines[0] = (monotonic() - 1, sequence, due_vehicle, slot)
            lot._condition.notify_all()
        lot.close(wait=True)
    finally:
        lot.close(wait=True)
    assert vehicle.state == "FINISHED"
    assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0


def test_concurrent_same_plate_admission_has_single_winner():
    from threading import Barrier

    contenders = 12
    lot = make_lot(1, [("A", True, 0)])
    lot.start()
    barrier = Barrier(contenders)
    results = [None] * contenders

    def contend(index):
        barrier.wait()
        results[index] = lot.admit(request(lot, index + 1, "A", .02))

    threads = [Thread(target=contend, args=(index,)) for index in range(contenders)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive()
        assert sum(result.accepted for result in results) == 1
        assert sum(result.reason == "DUPLICATE_ACTIVE" for result in results) == contenders - 1
    finally:
        lot.close()


def test_worker_startup_failure_joins_started_worker(monkeypatch):
    lot = make_lot()
    original_start = lot._departure_thread.start

    def fail_start():
        raise RuntimeError("controlled worker startup failure")

    monkeypatch.setattr(lot._departure_thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="controlled worker startup failure"):
        lot.start()
    assert not lot._admission_thread.is_alive()
    assert not lot._departure_started
    monkeypatch.setattr(lot._departure_thread, "start", original_start)


def test_sink_publication_failure_closes_and_drains_workers():
    class FailOnceQueue(Queue):
        def __init__(self):
            super().__init__()
            self.fail = True
            self.failed_put = Event()

        def put(self, item, *args, **kwargs):
            if self.fail:
                self.fail = False
                self.failed_put.set()
                raise OSError("controlled sink failure")
            return super().put(item, *args, **kwargs)

    q = FailOnceQueue()
    lot = make_lot(1, [("A", True, 0)], q)
    lot.start()
    admission_errors = []

    def admit():
        try:
            lot.admit(request(lot, 1, "A", .01))
        except OSError as error:
            admission_errors.append(error)

    admission = Thread(target=admit)
    admission.start()
    admission.join(3)
    assert not admission.is_alive()
    assert q.failed_put.is_set()
    with pytest.raises(RuntimeError, match="event publication failed"):
        lot.close(wait=True)
    assert admission_errors
    assert not lot._admission_thread.is_alive()
    assert not lot._departure_thread.is_alive()
    assert lot.snapshot().occupied_count == lot.snapshot().waiting_count == 0


def test_join_failure_can_be_retried_without_losing_drain(monkeypatch):
    lot = make_lot(1, [("A", True, 0)])
    lot.start()
    assert lot.admit(request(lot, 1, "A", .01)).accepted
    original_join = lot._admission_thread.join

    def fail_join(timeout=None):
        raise RuntimeError("controlled join failure")

    monkeypatch.setattr(lot._admission_thread, "join", fail_join)
    with pytest.raises(RuntimeError, match="controlled join failure"):
        lot.close(wait=True)
    monkeypatch.setattr(lot._admission_thread, "join", original_join)
    lot.close(wait=True)
    assert lot._drained
    assert not lot._admission_thread.is_alive()
    assert not lot._departure_thread.is_alive()
