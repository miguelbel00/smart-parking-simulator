"""Entry point for the parking simulator."""

from queue import Queue
import sys

from core.parking import ParkingLot
from simulation import config
from simulation.audit_logging import AuditSession
from simulation.authorizations import load_authorizations
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator
from ui.interface import ParkingApp


def main() -> None:
    """Compose the modules and run the parking simulator."""
    audit = AuditSession()
    simulator: Simulator | None = None
    primary_error: BaseException | None = None
    try:
        ui_queue: Queue = Queue()

        def run_factory() -> tuple[ParkingLot, MetricsForwardingQueue, SimulationMetrics]:
            metrics = SimulationMetrics()
            event_queue = MetricsForwardingQueue(destination=ui_queue, metrics=metrics)
            registry = load_authorizations(config.AUTHORIZATION_FILE, config.PARKING_CAPACITY)
            parking = ParkingLot(capacity=config.PARKING_CAPACITY, event_queue=event_queue,
                                 authorization_registry=registry)
            return parking, event_queue, metrics

        simulator = Simulator(run_factory=run_factory, plate_sequence=config.PLATE_SEQUENCE)
        simulator.set_audit(audit)

        app = ParkingApp(
            event_queue=ui_queue,
            simulator=simulator,
            capacity=config.PARKING_CAPACITY,
        )
        app.run()
    except BaseException as error:
        primary_error = error
        try:
            audit.exception("application", None, error)
        except BaseException as audit_error:
            print(f"Audit exception reporting failed: {audit_error}", file=sys.stderr)
        raise
    finally:
        try:
            if simulator is not None:
                try:
                    simulator.shutdown()
                except BaseException as error:
                    if primary_error is None:
                        raise
                    try:
                        audit.exception("shutdown", None, error)
                    except BaseException as audit_error:
                        print(f"Audit exception reporting failed: {audit_error}", file=sys.stderr)
        finally:
            try:
                audit.close()
            except BaseException as error:
                if primary_error is None:
                    raise
                print(f"Audit close failed: {error}", file=sys.stderr)

    if simulator.metrics is not None:
        print(simulator.metrics.report())


if __name__ == "__main__":
    main()
