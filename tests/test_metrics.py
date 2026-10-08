"""Tests for thread-safe simulation metrics."""

from simulation.metrics import SimulationMetrics


def test_average_wait_is_zero_without_samples() -> None:
    assert SimulationMetrics().snapshot().average_wait == 0.0


def test_average_wait_includes_immediate_entries_and_waits() -> None:
    metrics = SimulationMetrics()

    metrics.record_waiting_time(0.0)
    metrics.record_waiting_time(2.0)
    metrics.record_waiting_time(4.0)

    assert metrics.snapshot().average_wait == 2.0
