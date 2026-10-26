"""Headless projection of core parking events onto displayed slot keys."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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


@dataclass
class RequestRecord:
    """Canonical UI projection of a single vehicle request lifecycle."""

    vehicle_id: int
    plate: str | None = None
    authorized_slot: int | None = None
    occupied_slot: int | None = None
    state: str = "CREATED"
    waiting_time: float | None = None
    reason: str | None = None

    def as_table_row(self) -> tuple[str, str, str, str, str, str, str]:
        """Return 7 formatted display cells using '—' for unavailable fields."""
        return (
            f"#{self.vehicle_id}",
            self.plate if self.plate else "—",
            f"Puesto #{self.authorized_slot}" if self.authorized_slot is not None else "—",
            f"Puesto #{self.occupied_slot}" if self.occupied_slot is not None else "—",
            self.state,
            f"{self.waiting_time:.2f}s" if self.waiting_time is not None else "—",
            self.reason if self.reason else "—",
        )


class ParkingProjection:
    """Run-local display state; accessed only by the UI's event consumer."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.reset()

    def reset(self) -> None:
        self.occupied: dict[int, int] = {}
        # Plates of currently parked vehicles, keyed by vehicle ID.
        self.plates: dict[int, str] = {}
        self.waiting: set[int] = set()
        self._finished: set[int] = set()
        # Historical and active request records keyed by vehicle_id in observation order.
        self.requests: dict[int, RequestRecord] = {}
        # Accepted requests still pending entry (CREATED or WAITING), in acceptance order.
        self.pending_order: list[int] = []

    @property
    def occupied_count(self) -> int:
        return len(self.occupied)

    @property
    def available_count(self) -> int:
        return self.capacity - self.occupied_count

    @property
    def finished_count(self) -> int:
        return len(self._finished)

    @property
    def pending_count(self) -> int:
        return len(self.pending_order)

    def _optional_slot(self, space_id: int | None) -> int | None:
        if space_id is None:
            return None
        if isinstance(space_id, int) and 0 <= space_id < self.capacity:
            return space_id + 1
        return None

    def _ensure_record(
        self,
        vehicle_id: int,
        plate: str | None = None,
        authorized_slot: int | None = None,
    ) -> RequestRecord:
        record = self.requests.get(vehicle_id)
        if record is None:
            record = RequestRecord(
                vehicle_id=vehicle_id,
                plate=plate,
                authorized_slot=authorized_slot,
            )
            self.requests[vehicle_id] = record
        else:
            if plate:
                record.plate = plate
            if authorized_slot is not None:
                record.authorized_slot = authorized_slot
        return record

    def _add_pending(self, vehicle_id: int) -> None:
        if vehicle_id not in self.pending_order:
            self.pending_order.append(vehicle_id)

    def _remove_pending(self, vehicle_id: int) -> None:
        if vehicle_id in self.pending_order:
            self.pending_order.remove(vehicle_id)

    def pending_by_slot(self) -> dict[int | None, list[RequestRecord]]:
        """Group pending requests (CREATED or WAITING) by 1-based authorized slot.

        Preserves exact observed acceptance order within each slot group.
        """
        groups: dict[int | None, list[RequestRecord]] = {}
        for vid in self.pending_order:
            record = self.requests.get(vid)
            if record is None:
                continue
            groups.setdefault(record.authorized_slot, []).append(record)
        return groups

    def table_rows(self) -> list[tuple[str, str, str, str, str, str, str]]:
        """Return all observed requests formatted for the tracking table."""
        return [record.as_table_row() for record in self.requests.values()]

    def apply_event(self, event: ParkingEvent) -> int | None:
        """Fold a core event and return its projected slot when applicable."""
        auth_slot = self._optional_slot(getattr(event, "authorized_space_id", None))
        plate = getattr(event, "plate", None)
        reason = getattr(event, "reason", None)
        waiting_time = getattr(event, "waiting_time", None)

        if event.type == "SIMULATION_STARTED":
            self.reset()
        elif event.type == "VEHICLE_CREATED":
            if event.vehicle_id is not None:
                record = self._ensure_record(event.vehicle_id, plate, auth_slot)
                record.state = "CREATED"
                self._add_pending(event.vehicle_id)
        elif event.type == "VEHICLE_WAITING" and event.vehicle_id is not None:
            self.waiting.add(event.vehicle_id)
            record = self._ensure_record(event.vehicle_id, plate, auth_slot)
            record.state = "WAITING"
            self._add_pending(event.vehicle_id)
        elif event.type == "VEHICLE_ENTERED":
            if event.space_id is not None:
                slot = core_space_to_slot(event.space_id, self.capacity)
                if event.vehicle_id is not None:
                    self.occupied[slot] = event.vehicle_id
                    if plate:
                        self.plates[event.vehicle_id] = plate
            else:
                slot = None
            if event.vehicle_id is not None:
                self.waiting.discard(event.vehicle_id)
                self._remove_pending(event.vehicle_id)
                record = self._ensure_record(
                    event.vehicle_id,
                    plate,
                    auth_slot if auth_slot is not None else slot,
                )
                record.state = "ENTERED"
                record.occupied_slot = slot
                if waiting_time is not None:
                    record.waiting_time = float(waiting_time)
            return slot
        elif event.type == "VEHICLE_EXITED" and event.space_id is not None:
            slot = core_space_to_slot(event.space_id, self.capacity)
            self.occupied.pop(slot, None)
            if event.vehicle_id is not None:
                self.plates.pop(event.vehicle_id, None)
                self._remove_pending(event.vehicle_id)
                record = self._ensure_record(event.vehicle_id, plate, auth_slot)
                record.state = "EXITED"
                if record.occupied_slot is None:
                    record.occupied_slot = slot
            return slot
        elif event.type == "VEHICLE_FINISHED" and event.vehicle_id is not None:
            self.waiting.discard(event.vehicle_id)
            self._remove_pending(event.vehicle_id)
            self._finished.add(event.vehicle_id)
            record = self._ensure_record(event.vehicle_id, plate, auth_slot)
            record.state = "FINISHED"
        elif event.type == "VEHICLE_CANCELLED" and event.vehicle_id is not None:
            self.waiting.discard(event.vehicle_id)
            self._remove_pending(event.vehicle_id)
            record = self._ensure_record(event.vehicle_id, plate, auth_slot)
            record.state = "CANCELLED"
            record.occupied_slot = None
            if reason:
                record.reason = reason
        elif event.type == "VEHICLE_REJECTED" and event.vehicle_id is not None:
            record = self._ensure_record(event.vehicle_id, plate, auth_slot)
            record.state = "REJECTED"
            record.occupied_slot = None
            if reason:
                record.reason = reason
        return None

    def reconcile_snapshot(self, snapshot: ParkingSnapshot) -> None:
        """Replace occupancy; aggregate waiting counts cannot identify badges."""
        if snapshot.capacity != self.capacity:
            raise ValueError("Snapshot capacity differs from displayed capacity")
        self.occupied = project_occupied_spaces(snapshot.occupied_spaces, self.capacity)
        # Prefer plates reported by the snapshot; keep known plates otherwise.
        snapshot_plates = {
            request.vehicle_id: request.plate
            for request in snapshot.active_requests
            if request.state == "PARKED" and request.plate
        }
        self.plates = {
            vehicle_id: snapshot_plates.get(vehicle_id, self.plates.get(vehicle_id))
            for vehicle_id in self.occupied.values()
            if vehicle_id in snapshot_plates or vehicle_id in self.plates
        }
        if snapshot.active_requests:
            new_pending: list[int] = []
            for req in snapshot.active_requests:
                auth_slot = self._optional_slot(req.authorized_space_id)
                occ_slot = self._optional_slot(req.space_id)
                rec = self._ensure_record(req.vehicle_id, req.plate, auth_slot)
                if req.state == "PARKED":
                    rec.state = "ENTERED"
                    rec.occupied_slot = occ_slot
                else:
                    rec.state = req.state
                    rec.occupied_slot = None
                    new_pending.append(req.vehicle_id)
            self.pending_order = new_pending
