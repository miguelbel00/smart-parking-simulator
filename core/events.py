"""Shared event payload and vocabulary for parking and simulation."""

from dataclasses import dataclass


VEHICLE_CREATED = "VEHICLE_CREATED"
VEHICLE_WAITING = "VEHICLE_WAITING"
VEHICLE_ENTERED = "VEHICLE_ENTERED"
VEHICLE_EXITED = "VEHICLE_EXITED"
VEHICLE_FINISHED = "VEHICLE_FINISHED"
VEHICLE_REJECTED = "VEHICLE_REJECTED"
VEHICLE_CANCELLED = "VEHICLE_CANCELLED"
SIMULATION_STARTED = "SIMULATION_STARTED"
SIMULATION_FINISHED = "SIMULATION_FINISHED"


@dataclass(frozen=True)
class ParkingEvent:
    """Immutable message passed between producers and the shared event queue."""

    type: str
    timestamp: float
    vehicle_id: int | None = None
    space_id: int | None = None
    waiting_time: float | None = None
    plate: str | None = None
    authorized_space_id: int | None = None
    reason: str | None = None
