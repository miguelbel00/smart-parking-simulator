"""Entry point for the parking simulator."""

from queue import Queue

from core.parking import ParkingLot
from simulation import config
from simulation.authorizations import load_authorizations
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator
from ui.interface import ParkingApp


def main() -> None:
    """Compose the modules and run the parking simulator."""
    ui_queue: Queue = Queue()

    def run_factory() -> tuple[ParkingLot, MetricsForwardingQueue, SimulationMetrics]:
        metrics = SimulationMetrics()
        event_queue = MetricsForwardingQueue(destination=ui_queue, metrics=metrics)
        registry = load_authorizations(config.AUTHORIZATION_FILE, config.PARKING_CAPACITY)
        parking = ParkingLot(capacity=config.PARKING_CAPACITY, event_queue=event_queue,
                             authorization_registry=registry)
        return parking, event_queue, metrics

    simulator = Simulator(run_factory=run_factory, plate_sequence=config.PLATE_SEQUENCE)

    app = ParkingApp(
        event_queue=ui_queue,
        simulator=simulator,
        capacity=config.PARKING_CAPACITY,
    )
    app.run()

    if simulator.metrics is not None:
        print(simulator.metrics.report())


if __name__ == "__main__":
    main()
