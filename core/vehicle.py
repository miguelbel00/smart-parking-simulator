"""Independent vehicle worker delegating parking transitions to its lot."""

from __future__ import annotations

from threading import Thread
from time import sleep
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.parking import ParkingLot


class Vehicle(Thread):
    def __init__(self, vehicle_id: int, parking: ParkingLot,
                 parking_duration: float) -> None:
        super().__init__()
        self.vehicle_id = vehicle_id
        self.parking = parking
        self.parking_duration = parking_duration
        self._state = "CREATED"

    @property
    def state(self) -> str:
        return self.parking._vehicle_state(self)

    def run(self) -> None:
        space_id = self.parking._enter(self)
        if space_id is None:
            return
        try:
            sleep(self.parking_duration)
        finally:
            self.parking._exit(self, space_id)
