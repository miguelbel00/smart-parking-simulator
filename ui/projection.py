"""Headless projection of core parking events onto displayed slot keys."""

from __future__ import annotations

from collections.abc import Iterable

from core.events import ParkingEvent
from core.parking import ParkingSnapshot


def core_space_to_slot(space_id: int, capacity: int) -> int:
    """Translate a validated 0-based core space to a 1-based display key."""
    if not isinstance(space_id, int) or not 0 <= space_id < capacity:
        raise ValueError(f"Core space {space_id!r} is outside capacity {capacity}")
    return space_id + 1


def project_occupied_spaces(
    occupied_spaces: Iterable[tuple[int, int]], capacity: int
) -> dict[int, int]:
    """Project raw core snapshot pairs without changing the source values."""
    return {
        core_space_to_slot(space_id, capacity): vehicle_id
        for space_id, vehicle_id in occupied_spaces
    }


class ParkingProjection:
    """Run-local display state; accessed only by the UI's event consumer."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.reset()

    def reset(self) -> None:
        self.occupied: dict[int, int] = {}
        self.waiting: set[int] = set()
        self._finished: set[int] = set()

    @property
    def occupied_count(self) -> int:
        return len(self.occupied)

    @property
    def available_count(self) -> int:
        return self.capacity - self.occupied_count

    @property
    def finished_count(self) -> int:
        return len(self._finished)

    def apply_event(self, event: ParkingEvent) -> int | None:
        """Fold a core event and return its projected slot when applicable."""
        if event.type == "SIMULATION_STARTED":
            self.reset()
        elif event.type == "VEHICLE_WAITING" and event.vehicle_id is not None:
            self.waiting.add(event.vehicle_id)
        elif event.type == "VEHICLE_ENTERED":
            if event.space_id is not None:
                slot = core_space_to_slot(event.space_id, self.capacity)
                if event.vehicle_id is not None:
                    self.occupied[slot] = event.vehicle_id
            else:
                slot = None
            if event.vehicle_id is not None:
                self.waiting.discard(event.vehicle_id)
            return slot
        elif event.type == "VEHICLE_EXITED" and event.space_id is not None:
            slot = core_space_to_slot(event.space_id, self.capacity)
            self.occupied.pop(slot, None)
            return slot
        elif event.type == "VEHICLE_FINISHED" and event.vehicle_id is not None:
            self.waiting.discard(event.vehicle_id)
            self._finished.add(event.vehicle_id)
        return None

    def reconcile_snapshot(self, snapshot: ParkingSnapshot) -> None:
        """Replace occupancy; aggregate waiting counts cannot identify badges."""
        if snapshot.capacity != self.capacity:
            raise ValueError("Snapshot capacity differs from displayed capacity")
        self.occupied = project_occupied_spaces(snapshot.occupied_spaces, self.capacity)
