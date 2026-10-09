"""Simulation metrics collection."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any

from core.events import (
    SIMULATION_FINISHED,
    SIMULATION_STARTED,
    VEHICLE_ENTERED,
    VEHICLE_EXITED,
    VEHICLE_FINISHED,
    VEHICLE_WAITING,
)

if TYPE_CHECKING:
    from queue import Queue


class SimulationMetrics:
    """Thread-safe aggregation of parking events into final statistics.

    Vehicle threads and the Simulator publish events concurrently, so every
    counter is protected by a Lock, consistent with the project's rule that
    concurrent statistics are shared state (AGENTS.md section 5).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._generated = 0
        self._admitted = 0
        self._rejected = 0
        self._finished = 0
        self._waiting_times: list[float] = []
        self._parking_started_at: dict[int, float] = {}
        self._parking_durations: list[float] = []
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._currently_waiting: set[int] = set()
        self._currently_parked: set[int] = set()
        self._peak_waiting = 0
        self._peak_occupancy = 0

    def record_generated(self) -> None:
        with self._lock:
            self._generated += 1

    def record_admitted(self) -> None:
        with self._lock:
            self._admitted += 1

    def record_rejected(self) -> None:
        with self._lock:
            self._rejected += 1

    def record_event(self, event: Any) -> None:
        """Fold one ParkingEvent published by core or the Simulator."""
        with self._lock:
            if event.type == VEHICLE_WAITING:
                if event.vehicle_id is not None:
                    self._currently_waiting.add(event.vehicle_id)
                    self._peak_waiting = max(self._peak_waiting, len(self._currently_waiting))
            elif event.type == VEHICLE_ENTERED:
                if event.waiting_time is not None:
                    self._waiting_times.append(event.waiting_time)
                if event.vehicle_id is not None:
                    self._currently_waiting.discard(event.vehicle_id)
                    self._parking_started_at[event.vehicle_id] = event.timestamp
                    self._currently_parked.add(event.vehicle_id)
                    self._peak_occupancy = max(self._peak_occupancy, len(self._currently_parked))
            elif event.type == VEHICLE_EXITED:
                self._currently_parked.discard(event.vehicle_id)
                started_at = self._parking_started_at.pop(event.vehicle_id, None)
                if started_at is not None:
                    self._parking_durations.append(event.timestamp - started_at)
            elif event.type == VEHICLE_FINISHED:
                self._finished += 1
                self._currently_waiting.discard(event.vehicle_id)
            elif event.type == SIMULATION_STARTED:
                self._started_at = event.timestamp
            elif event.type == SIMULATION_FINISHED:
                self._finished_at = event.timestamp

    def snapshot(self) -> dict[str, float | int | None]:
        """Point-in-time copy of the collected statistics."""
        with self._lock:
            duration = (
                self._finished_at - self._started_at
                if self._started_at is not None and self._finished_at is not None
                else None
            )
            return {
                "total_generated": self._generated,
                "total_admitted": self._admitted,
                "total_rejected": self._rejected,
                "total_finished": self._finished,
                "average_waiting_time": _average(self._waiting_times),
                "average_parking_time": _average(self._parking_durations),
                "peak_waiting": self._peak_waiting,
                "peak_occupancy": self._peak_occupancy,
                "total_duration": duration,
            }

    def report(self) -> str:
        """Human-readable final statistics block."""
        stats = self.snapshot()
        duration = stats["total_duration"]
        duration_line = f"{duration:.2f}s" if duration is not None else "N/D"
        return (
            "--- Estadísticas finales de la simulación ---\n"
            f"Vehículos generados:                {stats['total_generated']}\n"
            f"Vehículos admitidos:                 {stats['total_admitted']}\n"
            f"Vehículos rechazados:                {stats['total_rejected']}\n"
            f"Vehículos que finalizaron su ciclo:  {stats['total_finished']}\n"
            f"Tiempo de espera promedio:           {stats['average_waiting_time']:.2f}s\n"
            f"Tiempo de estacionamiento promedio:  {stats['average_parking_time']:.2f}s\n"
            f"Máximo de vehículos en espera:        {stats['peak_waiting']}\n"
            f"Máxima ocupación alcanzada:           {stats['peak_occupancy']}\n"
            f"Duración total de la simulación:     {duration_line}\n"
        )


class MetricsForwardingQueue:
    """Queue-like object handed to `ParkingLot` and `Simulator` as their
    shared `event_queue`.

    `ParkingLot` only ever calls `put()` on its event queue, and the UI is
    the exclusive consumer draining it via `get_nowait()`. This object sits
    between the two: it forwards every event to the real UI queue unchanged
    and folds it into `SimulationMetrics` on the way, so metrics collection
    never competes with the UI for the same events.
    """

    def __init__(self, destination: Queue, metrics: SimulationMetrics) -> None:
        self._destination = destination
        self._metrics = metrics

    def put(self, item: Any, block: bool = True, timeout: float | None = None) -> None:
        self._metrics.record_event(item)
        self._destination.put(item, block=block, timeout=timeout)


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
