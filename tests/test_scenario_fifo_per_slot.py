"""Behavioral proof for the fifo_per_slot academic scenario.

Tier A drives the scenario in-process, mirroring exactly how the real
engine wires run_factory() in simulation/multiprocess.py (ParkingLot +
MetricsForwardingQueue + Simulator), without the process boundary.
Tier B drives the same scenario through the real spawn-based
MultiprocessController and its IPC transport, proving the behavior
survives serialization and the process boundary.

Both tiers assert outcomes read from the real event stream produced by
Core (admit/FIFO-per-slot/Semaphore/Condition); nothing here simulates
or re-implements an admission, FIFO, or authorization decision.
"""

from queue import Queue

import pytest

from core.events import (
    SIMULATION_FINISHED,
    VEHICLE_ENTERED,
    VEHICLE_EXITED,
    VEHICLE_FINISHED,
    VEHICLE_REJECTED,
    VEHICLE_WAITING,
)
from core.parking import ParkingLot
from simulation import config as simulation_config
from simulation.authorizations import load_authorizations
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.multiprocess import MultiprocessController
from simulation.scenarios import build_payload, get_scenario
from simulation.simulator import Simulator

# Integer seconds: simulation.ipc_protocol.validate_start_payload requires
# every config timing field to be a nonnegative int, so sub-second overrides
# are not representable through the real contract.
FAST_OVERRIDES = {
    "min_arrival_time": 0,
    "max_arrival_time": 0,
    "min_parking_time": 1,
    "max_parking_time": 1,
}


def test_fifo_per_slot_in_process_entry_order_and_mutual_exclusion(monkeypatch):
    scenario = get_scenario("fifo_per_slot")
    payload = build_payload("fifo_per_slot", overrides=FAST_OVERRIDES)
    values = payload["config"]

    # Mirrors exactly what simulation/multiprocess.py's _engine() does before
    # building a run: Simulator._run() reads arrival/parking bounds fresh
    # from this module on every iteration, with no constructor override hook.
    monkeypatch.setattr(simulation_config, "MIN_ARRIVAL_TIME", values["min_arrival_time"])
    monkeypatch.setattr(simulation_config, "MAX_ARRIVAL_TIME", values["max_arrival_time"])
    monkeypatch.setattr(simulation_config, "MIN_PARKING_TIME", values["min_parking_time"])
    monkeypatch.setattr(simulation_config, "MAX_PARKING_TIME", values["max_parking_time"])

    registry = load_authorizations(scenario.authorization_path, scenario.capacity)
    q: Queue = Queue()
    metrics = SimulationMetrics()
    forwarding = MetricsForwardingQueue(q, metrics)
    parking = ParkingLot(values["capacity"], forwarding, registry)

    def run_factory():
        return parking, forwarding, metrics

    simulator = Simulator(run_factory, payload["plate_sequence"])
    assert simulator.start()
    try:
        events = []
        while True:
            event = q.get(timeout=10)
            events.append(event)
            if event.type == SIMULATION_FINISHED:
                break
    finally:
        simulator.shutdown()

    _assert_fifo_per_slot_invariants(
        events,
        entered_plate=lambda event: event.plate,
        entered_space=lambda event: event.space_id,
        event_type=lambda event: event.type,
    )


def test_fifo_per_slot_via_multiprocess_controller_and_real_ipc():
    payload = build_payload("fifo_per_slot", overrides=FAST_OVERRIDES)
    controller = MultiprocessController(payload["config"]["capacity"], context="spawn")
    controller.start_engine()
    try:
        controller.start(payload)
        events = []
        while True:
            message = controller.get(timeout=20)
            if message.get("kind") == "failure":
                pytest.fail(f"engine failed: {message}")
            if message.get("kind") != "event":
                continue
            events.append(message)
            if message["name"] == SIMULATION_FINISHED:
                break
    finally:
        controller.shutdown()

    _assert_fifo_per_slot_invariants(
        events,
        entered_plate=lambda message: message["payload"]["plate"],
        entered_space=lambda message: message["payload"]["space_id"],
        event_type=lambda message: message["name"],
    )


def _assert_fifo_per_slot_invariants(events, entered_plate, entered_space, event_type):
    assert event_type(events[-1]) == SIMULATION_FINISHED

    entered = [event for event in events if event_type(event) == VEHICLE_ENTERED]
    # A and C enter immediately (free slots). B queues behind A for slot 0;
    # D arrives after B and queues behind it for the same slot, even though
    # C (slot 1) overtakes B - this is FIFO per authorized slot, not a
    # single global FIFO queue. On A's release, B enters before D.
    assert [entered_plate(event) for event in entered] == ["FIFO-A", "FIFO-C", "FIFO-B", "FIFO-D"]

    def index_of(name, plate):
        return next(i for i, event in enumerate(events)
                    if event_type(event) == name and entered_plate(event) == plate)

    assert index_of(VEHICLE_WAITING, "FIFO-B") < index_of(VEHICLE_ENTERED, "FIFO-B")
    assert index_of(VEHICLE_WAITING, "FIFO-D") < index_of(VEHICLE_ENTERED, "FIFO-D")

    occupied = {}
    for event in events:
        kind = event_type(event)
        if kind == VEHICLE_ENTERED:
            space_id = entered_space(event)
            assert space_id not in occupied, f"mutual exclusion violated on slot {space_id}"
            occupied[space_id] = entered_plate(event)
        elif kind == VEHICLE_EXITED:
            space_id = entered_space(event)
            assert occupied.pop(space_id) == entered_plate(event)
    assert not occupied

    assert sum(event_type(event) == VEHICLE_FINISHED for event in events) == 4
    assert sum(event_type(event) == VEHICLE_REJECTED for event in events) == 0
