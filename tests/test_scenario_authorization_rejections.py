"""Behavioral proof for the authorization_rejections academic scenario.

Tier A drives the scenario in-process, mirroring exactly how the real
engine wires run_factory() in simulation/multiprocess.py (ParkingLot +
MetricsForwardingQueue + Simulator), without the process boundary.
Tier B drives the same scenario through the real spawn-based
MultiprocessController and its IPC transport, proving the behavior
survives serialization and the process boundary.

Both tiers assert outcomes read from the real event stream produced by
Core (AuthorizationRegistry.lookup + ParkingLot.admit); nothing here
simulates or re-implements an authorization or admission decision.
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

SCENARIO_NAME = "authorization_rejections"

# Integer seconds: simulation.ipc_protocol.validate_start_payload requires
# every config timing field to be a nonnegative int, so sub-second overrides
# are not representable through the real contract.
FAST_OVERRIDES = {
    "min_arrival_time": 0,
    "max_arrival_time": 0,
    "min_parking_time": 1,
    "max_parking_time": 1,
}


def test_authorization_rejections_in_process(monkeypatch):
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

    _assert_authorization_rejection_invariants(
        events,
        event_type=lambda event: event.type,
        vehicle_id=lambda event: event.vehicle_id,
        plate_of=lambda event: event.plate,
        reason=lambda event: event.reason,
    )

    stats = metrics.snapshot()
    assert stats["total_rejected"] == 2
    assert stats["total_finished"] == 3
    assert stats["total_cancelled"] == 0
    assert stats["total_parked"] == 3


def test_authorization_rejections_via_multiprocess_controller_and_real_ipc():
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

    _assert_authorization_rejection_invariants(
        events,
        event_type=lambda message: message["name"],
        vehicle_id=lambda message: message["payload"]["vehicle_id"],
        plate_of=lambda message: message["payload"]["plate"],
        reason=lambda message: message["payload"]["reason"],
    )


def _assert_authorization_rejection_invariants(events, event_type, vehicle_id, plate_of, reason):
    assert event_type(events[-1]) == SIMULATION_FINISHED

    # D is authorized only for slot 0. It must wait for A to release that slot.
    def index_of(kind, wanted_plate):
        return next(index for index, event in enumerate(events)
                    if event_type(event) == kind and plate_of(event) == wanted_plate)

    assert index_of(VEHICLE_WAITING, "AUTH-D") < index_of(VEHICLE_ENTERED, "AUTH-D")
    assert index_of(VEHICLE_EXITED, "AUTH-A") < index_of(VEHICLE_ENTERED, "AUTH-D")

    rejected = {
        vehicle_id(event): reason(event)
        for event in events if event_type(event) == VEHICLE_REJECTED
    }
    # B is unknown; the second A request duplicates its active first request.
    assert rejected == {2: "UNKNOWN_PLATE", 4: "DUPLICATE_ACTIVE"}

    entered = [event for event in events if event_type(event) == VEHICLE_ENTERED]
    exited = [event for event in events if event_type(event) == VEHICLE_EXITED]
    finished = [event for event in events if event_type(event) == VEHICLE_FINISHED]
    assert [vehicle_id(event) for event in entered] == [1, 3, 5]
    assert [vehicle_id(event) for event in exited] == [1, 3, 5]
    assert [vehicle_id(event) for event in finished] == [1, 3, 5]
