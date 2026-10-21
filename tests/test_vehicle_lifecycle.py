"""Lifecycle event order and close behavior for request-based vehicles."""

from queue import Queue
from time import monotonic, sleep

from core.events import (VEHICLE_CREATED, VEHICLE_ENTERED, VEHICLE_EXITED,
                        VEHICLE_FINISHED, VEHICLE_WAITING)
from core.parking import ParkingLot
from core.vehicle import Vehicle
from simulation.authorizations import Authorization, AuthorizationRegistry


def test_created_entered_exit_finished_event_order():
    queue = Queue()
    registry = AuthorizationRegistry({"A": Authorization("A", True, 0)})
    lot = ParkingLot(1, queue, registry)
    lot.start()
    request = Vehicle(1, lot, .01, "A")
    assert lot.admit(request).accepted
    deadline = monotonic() + 2
    while lot.snapshot().occupied_count == 0:
        assert monotonic() < deadline
        sleep(.001)
    lot.close()
    assert request.state == "FINISHED"
    assert [e.type for e in queue.queue] == [VEHICLE_CREATED, VEHICLE_ENTERED,
                                              VEHICLE_EXITED, VEHICLE_FINISHED]


def test_close_cancellation_preserves_created_waiting_finished():
    queue = Queue()
    registry = AuthorizationRegistry({"A": Authorization("A", True, 0),
                                      "B": Authorization("B", True, 0)})
    lot = ParkingLot(1, queue, registry)
    lot.start()
    a = Vehicle(1, lot, .08, "A")
    b = Vehicle(2, lot, .01, "B")
    assert lot.admit(a).accepted and lot.admit(b).accepted
    deadline = monotonic() + 2
    while lot.snapshot().waiting_count != 1:
        assert monotonic() < deadline
        sleep(.002)
    lot.close()
    assert [e.type for e in queue.queue if e.vehicle_id == 2] == [
        VEHICLE_CREATED, VEHICLE_WAITING, VEHICLE_FINISHED,
    ]
    assert [e.type for e in queue.queue if e.vehicle_id == 1] == [
        VEHICLE_CREATED, VEHICLE_ENTERED, VEHICLE_EXITED, VEHICLE_FINISHED,
    ]
