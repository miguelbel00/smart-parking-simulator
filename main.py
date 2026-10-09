"""Entry point for the parking simulator."""

from queue import Queue

from core.parking import ParkingLot
from simulation import config
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator
from ui.interface import ParkingApp


def main() -> None:
    """Compose the modules and run the parking simulator."""
    ui_queue: Queue = Queue()
    metrics = SimulationMetrics()
    event_queue = MetricsForwardingQueue(destination=ui_queue, metrics=metrics)

    parking = ParkingLot(capacity=config.PARKING_CAPACITY, event_queue=event_queue)
    simulator = Simulator(parking=parking, event_queue=event_queue, metrics=metrics)

    app = ParkingApp(
        event_queue=ui_queue,
        simulator=simulator,
        capacity=config.PARKING_CAPACITY,
    )
    app.run()

    print(metrics.report())


if __name__ == "__main__":
    main()
