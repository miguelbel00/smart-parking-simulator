"""Behavioral proof for the capacity_saturation_and_release academic scenario.

Tier A drives the scenario in-process, mirroring exactly how the real
engine wires run_factory() in simulation/multiprocess.py (ParkingLot +
MetricsForwardingQueue + Simulator), without the process boundary.
Tier B drives the same scenario through the real spawn-based
MultiprocessController and its IPC transport, proving the behavior
survives serialization and the process boundary.

Both tiers assert outcomes read from the real event stream produced by
Core (admit/FIFO-per-slot/Semaphore/Condition); nothing here simulates
or re-implements an admission, FIFO, capacity, or authorization decision.
"""

from queue import Queue

import pytest

from core.events import (
    SIMULATION_FINISHED,
    VEHICLE_CANCELLED,
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

SCENARIO_NAME = "capacity_saturation_and_release"

# Integer seconds: simulation.ipc_protocol.validate_start_payload requires
# every config timing field to be a nonnegative int, so sub-second overrides
# are not representable through the real contract.
FAST_OVERRIDES = {
    "min_arrival_time": 0,
    "max_arrival_time": 0,
    "min_parking_time": 1,
    "max_parking_time": 1,
}


def test_capacity_saturation_in_process_peak_occupancy_and_release(monkeypatch):
    scenario = get_scenario(SCENARIO_NAME)
    payload = build_payload(SCENARIO_NAME, overrides=FAST_OVERRIDES)
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

    _assert_capacity_saturation_invariants(
        events,
        capacity=values["capacity"],
        entered_plate=lambda event: event.plate,
        entered_space=lambda event: event.space_id,
        event_type=lambda event: event.type,
    )

    # Cross-check the manually reconstructed peak against the canonical
    # metric; never trust a parallel calculation over the real one when
    # it's reachable, as here (Tier B crosses a process boundary and the
    # SimulationMetrics object isn't, so it derives occupancy manually).
    assert metrics.snapshot()["peak_occupancy"] == values["capacity"]


def test_capacity_saturation_via_multiprocess_controller_and_real_ipc():
    payload = build_payload(SCENARIO_NAME, overrides=FAST_OVERRIDES)
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

    _assert_capacity_saturation_invariants(
        events,
        capacity=payload["config"]["capacity"],
        entered_plate=lambda message: message["payload"]["plate"],
        entered_space=lambda message: message["payload"]["space_id"],
        event_type=lambda message: message["name"],
    )


def _assert_capacity_saturation_invariants(events, capacity, entered_plate, entered_space, event_type):
    assert event_type(events[-1]) == SIMULATION_FINISHED

    def index_of(name, plate):
        return next(i for i, event in enumerate(events)
                    if event_type(event) == name and entered_plate(event) == plate)

    # SAT-A, SAT-B, SAT-C find their authorized slot free on arrival: no
    # WAITING precedes their ENTERED.
    for plate in ("SAT-A", "SAT-B", "SAT-C"):
        entered_at = index_of(VEHICLE_ENTERED, plate)
        waiting_before = [
            index for index, event in enumerate(events)
            if event_type(event) == VEHICLE_WAITING and entered_plate(event) == plate and index < entered_at
        ]
        assert not waiting_before, f"{plate} should not wait before entering"

    # SAT-D (slot 0) and SAT-E (slot 1) each wait, and only enter once the
    # earlier occupant of their *own* slot has exited - not on any other
    # vehicle's departure.
    assert index_of(VEHICLE_WAITING, "SAT-D") < index_of(VEHICLE_ENTERED, "SAT-D")
    assert index_of(VEHICLE_EXITED, "SAT-A") < index_of(VEHICLE_ENTERED, "SAT-D")

    assert index_of(VEHICLE_WAITING, "SAT-E") < index_of(VEHICLE_ENTERED, "SAT-E")
    assert index_of(VEHICLE_EXITED, "SAT-B") < index_of(VEHICLE_ENTERED, "SAT-E")

    # Mutual exclusion per slot, and simultaneous peak occupancy reconstructed
    # strictly from the real event stream (never exceeds and does reach
    # capacity, proving the Semaphore invariant from observed behavior).
    occupied = {}
    concurrent = 0
    peak = 0
    for event in events:
        kind = event_type(event)
        if kind == VEHICLE_ENTERED:
            space_id = entered_space(event)
            assert space_id not in occupied, f"mutual exclusion violated on slot {space_id}"
            occupied[space_id] = entered_plate(event)
            concurrent += 1
            peak = max(peak, concurrent)
        elif kind == VEHICLE_EXITED:
            space_id = entered_space(event)
            assert occupied.pop(space_id) == entered_plate(event)
            concurrent -= 1
    assert not occupied
    assert concurrent == 0
    assert peak == capacity

    assert sum(event_type(event) == VEHICLE_FINISHED for event in events) == 12
    assert sum(event_type(event) == VEHICLE_REJECTED for event in events) == 0
    assert sum(event_type(event) == VEHICLE_CANCELLED for event in events) == 0
