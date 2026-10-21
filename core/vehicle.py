"""Vehicle request data; vehicle requests are not threads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.parking import ParkingLot


@dataclass(eq=False)
class Vehicle:
    vehicle_id: int
    parking: ParkingLot
    parking_duration: float
    plate: str
    _state: str = field(default="CREATED", init=False, repr=False)

    @property
    def state(self) -> str:
        return self.parking._vehicle_state(self)
