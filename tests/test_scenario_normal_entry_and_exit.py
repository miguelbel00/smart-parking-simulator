"""Behavioral proof for the normal_entry_and_exit academic scenario.

Baseline, in-process only: one authorized vehicle, no contention, no
rejection, a natural finish. Contrasts against the other scenarios by
showing the simplest possible real Core run. Nothing here simulates or
re-implements an admission or lifecycle decision; events are read from
the real queue produced by ParkingLot/Simulator.
"""

from queue import Queue

from core.events import (
    SIMULATION_FINISHED,
    SIMULATION_STARTED,
    VEHICLE_CREATED,
    VEHICLE_ENTERED,
    VEHICLE_EXITED,
    VEHICLE_FINISHED,
)
from core.parking import ParkingLot
from simulation import config as simulation_config
from simulation.authorizations import load_authorizations
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.scenarios import build_payload, get_scenario
from simulation.simulator import Simulator

SCENARIO_NAME = "normal_entry_and_exit"

FAST_OVERRIDES = {
    "min_arrival_time": 0,
    "max_arrival_time": 0,
    "min_parking_time": 1,
    "max_parking_time": 1,
}


def test_normal_entry_and_exit_in_process(monkeypatch):
    scenario = get_scenario(SCENARIO_NAME)
    payload = build_payload(SCENARIO_NAME, overrides=FAST_OVERRIDES)
    values = payload["config"]

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

    assert [event.type for event in events] == [
        SIMULATION_STARTED,
        VEHICLE_CREATED,
        VEHICLE_ENTERED,
        VEHICLE_EXITED,
        VEHICLE_FINISHED,
        SIMULATION_FINISHED,
    ]

    stats = metrics.snapshot()
    assert stats["total_generated"] == 1
    assert stats["total_admitted"] == 1
    assert stats["total_rejected"] == 0
    assert stats["total_parked"] == 1
    assert stats["total_finished"] == 1
    assert stats["total_cancelled"] == 0
