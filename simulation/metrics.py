"""Thread-safe simulation-level metrics.

Lifecycle details emitted by core stay in the shared UI queue. Metrics do not
consume that queue: processed means accepted by ``ParkingLot.admit`` and
waiting/occupancy peaks are safe snapshot observations, not event-level exact
peaks. Core does not expose per-vehicle wait data except through its events.
"""

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class MetricsSnapshot:
    created: int
    processed: int
    average_wait: float
    peak_waiting: int
    peak_occupancy: int


class SimulationMetrics:
    """Collect admission counters and peaks observed through public snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._created = 0
        self._processed = 0
        self._total_waiting_time = 0.0
        self._waiting_time_samples = 0
        self._peak_waiting = 0
        self._peak_occupancy = 0

    def record_created(self) -> None:
        with self._lock:
            self._created += 1

    def record_waiting_time(self, waiting_time: float) -> None:
        with self._lock:
            self._total_waiting_time += waiting_time
            self._waiting_time_samples += 1

    def record_admission(self, accepted: bool, parking_snapshot: object) -> None:
        with self._lock:
            if accepted:
                self._processed += 1
            self._peak_waiting = max(self._peak_waiting, parking_snapshot.waiting_count)
            self._peak_occupancy = max(self._peak_occupancy, parking_snapshot.occupied_count)

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                created=self._created,
                processed=self._processed,
                average_wait=(
                    self._total_waiting_time / self._waiting_time_samples
                    if self._waiting_time_samples
                    else 0.0
                ),
                peak_waiting=self._peak_waiting,
                peak_occupancy=self._peak_occupancy,
            )
