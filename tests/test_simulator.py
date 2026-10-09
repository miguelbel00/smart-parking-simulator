"""Real, short-run regression tests for simulator ownership and lifecycle."""

from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from core.events import (SIMULATION_FINISHED, SIMULATION_STARTED, VEHICLE_CREATED,
                         VEHICLE_ENTERED, VEHICLE_FINISHED, VEHICLE_WAITING, ParkingEvent)
from core.parking import ParkingLot
from simulation import config
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator
import simulation.simulator as simulator_module


def await_exit(simulator, timeout=3):
    deadline = monotonic() + timeout
    while simulator.is_active() and monotonic() < deadline:
        sleep(0.001)
    assert not simulator.is_active(), "run did not exit"


def events_from(queue):
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except Empty:
            return events


@pytest.fixture
def short_runs(monkeypatch):
    monkeypatch.setattr(config, "TOTAL_VEHICLES", 2)
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0.02)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0.02)
    monkeypatch.setattr(config, "MIN_PARKING_TIME", 0.1)
    monkeypatch.setattr(config, "MAX_PARKING_TIME", 0.1)


def test_consecutive_runs_use_fresh_lots_metrics_and_forward_same_events(short_runs):
    destination = Queue()
    resources = []

    def factory():
        metrics = SimulationMetrics()
        forwarder = MetricsForwardingQueue(destination, metrics)
        lot = ParkingLot(capacity=1, event_queue=forwarder)
        resources.append((lot, forwarder, metrics))
        return resources[-1]

    simulator = Simulator(run_factory=factory)
    assert simulator.metrics is None
    for _ in range(2):
        assert simulator.start() is True
        assert simulator.start() is False
        await_exit(simulator)
        assert simulator.is_drained() is True
        run_events = events_from(destination)
        types = [event.type for event in run_events]
        assert types[0] == SIMULATION_STARTED
        assert types[-1] == SIMULATION_FINISHED
        assert types.count(SIMULATION_STARTED) == types.count(SIMULATION_FINISHED) == 1
        assert types.count(VEHICLE_CREATED) == types.count(VEHICLE_FINISHED) == 2
        assert all(event.type != VEHICLE_FINISHED for event in run_events[types.index(SIMULATION_FINISHED) + 1:])
        stats = simulator.metrics.snapshot()
        assert stats["total_generated"] == stats["total_admitted"] == stats["total_finished"] == 2
        assert stats["total_rejected"] == 0
        assert stats["peak_occupancy"] == 1
        assert stats["total_duration"] is not None
    assert resources[0][0] is not resources[1][0]
    assert resources[0][2] is not resources[1][2]
    assert simulator.metrics is resources[1][2]
    marker = ParkingEvent(type=SIMULATION_STARTED, timestamp=1.0)
    resources[1][1].put(marker)
    assert destination.get_nowait() is marker
    assert destination.empty()


def test_finish_publication_refuses_restart_until_actual_thread_exit(short_runs, monkeypatch):
    monkeypatch.setattr(config, "TOTAL_VEHICLES", 0)
    destination = Queue()
    published = Event()
    release = Event()
    lots = []

    class PausingForwarder(MetricsForwardingQueue):
        def put(self, item, block=True, timeout=None):
            super().put(item, block=block, timeout=timeout)
            if item.type == SIMULATION_FINISHED and len(lots) == 1:
                published.set()
                assert release.wait(3)

    def factory():
        metrics = SimulationMetrics()
        forwarder = PausingForwarder(destination, metrics)
        lot = ParkingLot(1, forwarder)
        lots.append(lot)
        return lot, forwarder, metrics

    simulator = Simulator(run_factory=factory)
    try:
        assert simulator.start() is True
        assert published.wait(3)
        assert simulator.is_active()
        assert simulator.start() is False
        assert len(lots) == 1
    finally:
        release.set()
        await_exit(simulator)
    assert simulator.start() is True
    await_exit(simulator)
    assert len(lots) == 2
    assert [e.type for e in events_from(destination)] == [SIMULATION_STARTED, SIMULATION_FINISHED] * 2


def test_stop_serializes_with_admission_and_drains_waiting(short_runs, monkeypatch):
    monkeypatch.setattr(config, "TOTAL_VEHICLES", 20)
    monkeypatch.setattr(config, "MIN_PARKING_TIME", 0.15)
    monkeypatch.setattr(config, "MAX_PARKING_TIME", 0.15)
    destination = Queue()
    metrics = SimulationMetrics()
    forwarder = MetricsForwardingQueue(destination, metrics)
    lot = ParkingLot(1, forwarder)
    simulator = Simulator(run_factory=lambda: (lot, forwarder, metrics))
    try:
        assert simulator.start() is True
        deadline = monotonic() + 3
        while lot.snapshot().waiting_count == 0 and monotonic() < deadline:
            sleep(0.001)
        assert lot.snapshot().waiting_count > 0
        simulator.stop()
        admitted_at_stop = metrics.snapshot()["total_admitted"]
        await_exit(simulator)
        assert metrics.snapshot()["total_admitted"] == admitted_at_stop
        assert simulator.is_drained()
        types = [e.type for e in events_from(destination)]
        assert VEHICLE_WAITING in types
        assert types[-1] == SIMULATION_FINISHED
        assert types.count(VEHICLE_CREATED) == types.count(VEHICLE_FINISHED)
        assert metrics.snapshot()["total_finished"] == admitted_at_stop
    finally:
        simulator.stop()
        await_exit(simulator)


def test_stop_during_arrival_wait_prevents_generation(short_runs, monkeypatch):
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0.2)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0.2)
    destination = Queue()
    metrics = SimulationMetrics()
    forwarder = MetricsForwardingQueue(destination, metrics)
    simulator = Simulator(run_factory=lambda: (ParkingLot(1, forwarder), forwarder, metrics))
    assert simulator.start() is True
    assert destination.get(timeout=3).type == SIMULATION_STARTED
    simulator.stop()
    await_exit(simulator)
    assert [e.type for e in events_from(destination)] == [SIMULATION_FINISHED]
    assert metrics.snapshot()["total_generated"] == 0


def test_stop_waits_for_inflight_admission_boundary(short_runs, monkeypatch):
    monkeypatch.setattr(config, "TOTAL_VEHICLES", 2)
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    entered_boundary = Event()
    release_boundary = Event()
    stop_returned = Event()
    real_vehicle = simulator_module.Vehicle

    def delayed_vehicle(*args, **kwargs):
        entered_boundary.set()
        assert release_boundary.wait(3)
        return real_vehicle(*args, **kwargs)

    monkeypatch.setattr(simulator_module, "Vehicle", delayed_vehicle)
    destination = Queue()
    metrics = SimulationMetrics()
    forwarder = MetricsForwardingQueue(destination, metrics)
    simulator = Simulator(run_factory=lambda: (ParkingLot(1, forwarder), forwarder, metrics))
    assert simulator.start() is True
    stopper = None
    try:
        assert entered_boundary.wait(3)
        stopper = Thread(target=lambda: (simulator.stop(), stop_returned.set()))
        stopper.start()
        assert not stop_returned.wait(0.02)
    finally:
        release_boundary.set()
        if stopper is not None:
            stopper.join(timeout=3)
        simulator.stop()
        await_exit(simulator)
    assert stop_returned.is_set()
    assert metrics.snapshot()["total_generated"] == 1
    assert metrics.snapshot()["total_admitted"] == 1
    assert [e.type for e in events_from(destination)][-1] == SIMULATION_FINISHED


def test_generation_error_closes_lot_and_publishes_finish(short_runs, monkeypatch):
    import threading

    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    monkeypatch.setattr(config, "TOTAL_VEHICLES", 1)
    monkeypatch.setattr(simulator_module.random, "uniform", lambda *_: (_ for _ in ()).throw(ValueError("arrival")))
    destination = Queue()
    metrics = SimulationMetrics()
    forwarder = MetricsForwardingQueue(destination, metrics)
    lot = ParkingLot(1, forwarder)
    simulator = Simulator(run_factory=lambda: (lot, forwarder, metrics))
    assert simulator.start() is True
    await_exit(simulator)
    assert simulator.is_drained()
    assert [e.type for e in events_from(destination)] == [SIMULATION_STARTED, SIMULATION_FINISHED]
    assert len(errors) == 1 and str(errors[0]) == "arrival"
    assert lot.admit(simulator_module.Vehicle(99, lot, 0)) is False


def test_close_failure_does_not_claim_drain_or_publish_finish(short_runs, monkeypatch):
    import threading

    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    monkeypatch.setattr(config, "TOTAL_VEHICLES", 0)
    destination = Queue()
    metrics = SimulationMetrics()
    forwarder = MetricsForwardingQueue(destination, metrics)

    class BrokenLot(ParkingLot):
        def close(self, wait=True):
            raise RuntimeError("close failed")

    simulator = Simulator(run_factory=lambda: (BrokenLot(1, forwarder), forwarder, metrics))
    assert simulator.start() is True
    await_exit(simulator)
    assert not simulator.is_drained()
    assert len(errors) == 1 and str(errors[0]) == "close failed"
    assert [e.type for e in events_from(destination)] == [SIMULATION_STARTED]
