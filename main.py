"""Entry point for the parking simulator."""

from queue import Queue

from core.parking import ParkingLot
from simulation.config import PARKING_CAPACITY
from simulation.simulator import Simulator
from ui.interface import ParkingApp


def main() -> None:
    """Compose the application and cleanly stop its workers on exit."""
    event_queue = Queue()
    parking = ParkingLot(capacity=PARKING_CAPACITY, event_queue=event_queue)
    simulator = Simulator(parking=parking, event_queue=event_queue)
    app = ParkingApp(
        event_queue=event_queue,
        simulator=simulator,
        capacity=PARKING_CAPACITY,
    )

    try:
        app.run()
    finally:
        simulator.stop()
        parking.close(wait=True)


if __name__ == "__main__":
    main()
