from queue import Empty, Queue
from threading import Event
from time import monotonic, sleep

import pytest

from core.events import (SIMULATION_FINISHED, SIMULATION_STARTED, VEHICLE_CREATED,
                         VEHICLE_FINISHED, VEHICLE_REJECTED, VEHICLE_CANCELLED)
from core.parking import ParkingLot
from simulation.authorizations import Authorization, AuthorizationRegistry, load_authorizations
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator
from test_parking import (assert_closed_resources, drain_with_controlled_deadlines,
                          expire_occupied, pause_admission_publication)


def setup_run(plates, capacity=1, registry=None, durations=None):
    destination = Queue()
    latest = []
    auth = registry or AuthorizationRegistry({plate: Authorization(plate, True, 0)
                                               for plate in set(plates)})

    def factory():
        metrics = SimulationMetrics()
        queue = MetricsForwardingQueue(destination, metrics)
        lot = ParkingLot(capacity, queue, auth)
        latest.append((lot, queue, metrics))
        return lot, queue, metrics

    simulator = Simulator(factory, plates, duration_factory=(lambda: .01) if durations is None else durations)
    return simulator, destination, latest


def wait_exit(simulator):
    limit = monotonic() + 3
    while simulator.is_active() and monotonic() < limit:
        sleep(.002)
    assert not simulator.is_active()


def drain(queue):
    result = []
    while True:
        try:
            result.append(queue.get_nowait())
        except Empty:
            return result


def test_fresh_runs_and_terminal_event_after_drain(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    simulator, queue, runs = setup_run(["A", "B"])
    for _ in range(2):
        assert simulator.start()
        wait_exit(simulator)
        types = [event.type for event in drain(queue)]
        assert types[0] == SIMULATION_STARTED and types[-1] == SIMULATION_FINISHED
        assert types.count(VEHICLE_CREATED) == types.count(VEHICLE_FINISHED) == 2
        assert simulator.is_drained()
    assert runs[0][0] is not runs[1][0]
    assert runs[0][2] is not runs[1][2]


def test_rejections_are_counted_only_from_forwarded_event(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    auth = AuthorizationRegistry({"NO": Authorization("NO", False, None)})
    simulator, queue, runs = setup_run(["NO"], registry=auth)
    assert simulator.start()
    wait_exit(simulator)
    events = drain(queue)
    rejected = [item for item in events if item.type == VEHICLE_REJECTED]
    assert len(rejected) == 1
    assert rejected[0].reason == "NOT_AUTHORIZED"
    assert rejected[0].plate == "NO" and rejected[0].space_id is None
    assert not any(item.type == VEHICLE_CREATED for item in events)
    stats = simulator.metrics.snapshot()
    assert (stats["total_generated"], stats["total_admitted"], stats["total_rejected"]) == (1, 0, 1)
    assert stats["total_finished"] == stats["total_cancelled"] == 0


def test_metrics_count_normal_finish_and_cancellation_from_distinct_events():
    metrics = SimulationMetrics()
    destination = Queue()
    queue = MetricsForwardingQueue(destination, metrics)
    from core.events import ParkingEvent
    queue.put(ParkingEvent("VEHICLE_FINISHED", 1.0, vehicle_id=1))
    queue.put(ParkingEvent(VEHICLE_CANCELLED, 2.0, vehicle_id=2, reason="STOP_REQUESTED"))
    stats = metrics.snapshot()
    assert stats["total_finished"] == 1
    assert stats["total_cancelled"] == 1


def test_restart_waits_for_producer_to_exit_after_finish_publication(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    destination = Queue()
    finish_published, release_finish = Event(), Event()
    runs = []

    class PausingQueue(MetricsForwardingQueue):
        def put(self, item, block=True, timeout=None):
            super().put(item, block=block, timeout=timeout)
            if item.type == SIMULATION_FINISHED and len(runs) == 1:
                finish_published.set()
                assert release_finish.wait(5)

    def factory():
        metrics = SimulationMetrics()
        queue = PausingQueue(destination, metrics)
        lot = ParkingLot(1, queue, AuthorizationRegistry({}))
        runs.append((lot, queue, metrics))
        return lot, queue, metrics

    simulator = Simulator(factory, [])
    try:
        assert simulator.start()
        assert finish_published.wait(3)
        assert simulator.is_active()
        assert not simulator.start()
        assert len(runs) == 1
    finally:
        release_finish.set()
    wait_exit(simulator)
    assert simulator.start()
    wait_exit(simulator)
    assert len(runs) == 2


def test_stop_waits_for_inflight_admission_boundary(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    entered_admit, release_admit = Event(), Event()
    destination = Queue()
    metrics = SimulationMetrics()
    forwarder = MetricsForwardingQueue(destination, metrics)
    registry = AuthorizationRegistry({"A": Authorization("A", True, 0)})
    lots = []

    def factory():
        lot = ParkingLot(1, forwarder, registry)
        actual_admit = lot.admit

        def paused_admit(vehicle):
            entered_admit.set()
            assert release_admit.wait(2)
            return actual_admit(vehicle)

        lot.admit = paused_admit
        lots.append(lot)
        return lot, forwarder, metrics

    simulator = Simulator(factory, ["A"], duration_factory=lambda: .01)
    assert simulator.start() and entered_admit.wait(2)
    simulator.stop()
    release_admit.set()
    wait_exit(simulator)
    assert lots[0].snapshot().occupied_count == 0
    stats = simulator.metrics.snapshot()
    assert stats["total_generated"] == 1
    assert stats["total_admitted"] == 0
    types = [event.type for event in drain(destination)]
    assert types[-1] == SIMULATION_FINISHED and VEHICLE_CREATED not in types


def test_stop_after_commit_drains_parked_before_finish(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    simulator, queue, runs = setup_run(["A"], durations=lambda: .08)
    assert simulator.start()
    limit = monotonic() + 2
    while runs[0][0].snapshot().occupied_count == 0 and monotonic() < limit:
        sleep(.002)
    assert runs[0][0].snapshot().occupied_count == 1
    simulator.stop()
    wait_exit(simulator)
    events = drain(queue)
    types = [event.type for event in events]
    assert types[-1] == SIMULATION_FINISHED
    assert types.index(VEHICLE_FINISHED) < len(types) - 1


def test_invalid_authorization_file_fails_before_task_start(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"vehicles": [}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_authorizations(bad_file, 1)

    factory_called = Event()
    def factory():
        factory_called.set()
        raise AssertionError("invalid config should fail in composition")
    simulator = Simulator(factory, ["A"])
    assert not simulator.is_active()
    assert not factory_called.is_set()


@pytest.mark.parametrize("stop_after_natural_close", [True, False])
def test_stop_at_natural_drain_boundary_cancels_pending(monkeypatch, stop_after_natural_close):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    boundary, resume, natural_committed = Event(), Event(), Event()
    admission_gates = []
    simulator, queue, runs = setup_run(["A", "B", "C"], durations=lambda: 3600)
    original_factory = simulator._run_factory

    def factory():
        lot, forwarder, metrics = original_factory()
        admission_gates.append(pause_admission_publication(lot, monkeypatch))
        actual_admit, actual_close = lot.admit, lot.close

        def admit(vehicle):
            result = actual_admit(vehicle)
            if vehicle.vehicle_id == 1:
                with lot._condition:
                    assert lot._condition.wait_for(lambda: bool(lot._occupied), timeout=2)
            return result

        def close(wait=True, cancel_pending=True):
            if not cancel_pending:
                if stop_after_natural_close:
                    actual_close(wait=False, cancel_pending=False)
                boundary.set()
                assert resume.wait(5), "test did not release natural close"
                actual_close(wait=False, cancel_pending=False)
                natural_committed.set()
            return actual_close(wait=wait, cancel_pending=cancel_pending)

        monkeypatch.setattr(lot, "admit", admit)
        monkeypatch.setattr(lot, "close", close)
        return lot, forwarder, metrics

    monkeypatch.setattr(simulator, "_run_factory", factory)
    try:
        assert simulator.start()
        assert boundary.wait(2)
        lot = runs[0][0]
        assert lot.snapshot().occupied_spaces == ((0, 1),)
        assert lot.snapshot().waiting_count == 2
        simulator.stop()
        simulator.stop()
        resume.set()
        assert natural_committed.wait(2)
        admission_gates[0][1].set()
        with lot._condition:
            assert lot._condition.wait_for(lambda: not lot._pending, timeout=2)
        assert simulator.is_active() and not simulator.is_drained()
        assert lot.snapshot().occupied_spaces == ((0, 1),)
        expire_occupied(lot)
        wait_exit(simulator)
        simulator.stop()
        events = drain(queue)
        assert events[0].type == SIMULATION_STARTED
        assert events[-1].type == SIMULATION_FINISHED
        assert sum(event.type == SIMULATION_FINISHED for event in events) == 1
        terminals = [event for event in events if event.type in (VEHICLE_FINISHED, VEHICLE_CANCELLED)]
        assert sorted((event.vehicle_id, event.type) for event in terminals) == [
            (1, VEHICLE_FINISHED), (2, VEHICLE_CANCELLED), (3, VEHICLE_CANCELLED)]
        assert all(event.reason == "STOP_REQUESTED" for event in terminals if event.type == VEHICLE_CANCELLED)
        assert [event.vehicle_id for event in events if event.type == "VEHICLE_ENTERED"] == [1]
        stats = simulator.metrics.snapshot()
        assert (stats["total_generated"], stats["total_admitted"], stats["total_finished"],
                stats["total_cancelled"], stats["total_rejected"]) == (3, 3, 1, 2, 0)
        assert simulator.is_drained()
        assert_closed_resources(lot)
    finally:
        resume.set()
        for _, release_admission in admission_gates:
            release_admission.set()
        if runs:
            drain_with_controlled_deadlines(runs[0][0])
        simulator.shutdown()
