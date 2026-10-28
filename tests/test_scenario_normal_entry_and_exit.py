"""Behavioral proof for the normal_entry_and_exit scenario.

The in-process run observes full occupancy, pending requests, and natural
completion of every authorized vehicle through real Core events.
"""

from queue import Queue

from core.events import (
    SIMULATION_FINISHED,
    SIMULATION_STARTED,
    VEHICLE_CREATED,
    VEHICLE_ENTERED,
    VEHICLE_EXITED,
    VEHICLE_FINISHED,
    VEHICLE_WAITING,
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

    assert events[0].type == SIMULATION_STARTED
    assert events[-1].type == SIMULATION_FINISHED
    assert sum(event.type == VEHICLE_CREATED for event in events) == 30
    assert sum(event.type == VEHICLE_ENTERED for event in events) == 30
    assert sum(event.type == VEHICLE_EXITED for event in events) == 30
    assert sum(event.type == VEHICLE_FINISHED for event in events) == 30
    assert sum(event.type == VEHICLE_WAITING for event in events) > 0

    stats = metrics.snapshot()
    assert stats["total_generated"] == 30
    assert stats["total_admitted"] == 30
    assert stats["total_rejected"] == 0
    assert stats["total_parked"] == 30
    assert stats["total_finished"] == 30
    assert stats["total_cancelled"] == 0
    assert stats["peak_occupancy"] == scenario.capacity
