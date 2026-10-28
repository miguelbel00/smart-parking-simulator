"""Tests for thread-safe simulation metrics."""

from core.events import ParkingEvent
from simulation.metrics import SimulationMetrics


def test_average_wait_is_zero_without_samples() -> None:
    assert SimulationMetrics().snapshot()["average_waiting_time"] == 0.0


def test_average_wait_includes_immediate_entries_and_waits() -> None:
    metrics = SimulationMetrics()

    for vehicle_id, waiting_time in enumerate((0.0, 2.0, 4.0), start=1):
        metrics.record_event(ParkingEvent(
            "VEHICLE_ENTERED",
            float(vehicle_id),
            vehicle_id=vehicle_id,
            space_id=vehicle_id - 1,
            waiting_time=waiting_time,
        ))

    assert metrics.snapshot()["average_waiting_time"] == 2.0
