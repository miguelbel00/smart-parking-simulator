"""Entry point for the parking simulator."""

from queue import Queue
import sys

from simulation import config
from simulation.audit_logging import AuditSession
from simulation.authorizations import load_authorizations
from simulation.multiprocess import MultiprocessController
from simulation.scenarios import build_payload, get_scenario, list_academic_scenarios
from ui.interface import ParkingApp
from ui.multiprocess_adapter import MultiprocessGUIAdapter


def main() -> None:
    """Compose the modules and run the parking simulator."""
    audit = AuditSession()
    simulator: MultiprocessGUIAdapter | None = None
    primary_error: BaseException | None = None
    try:
        ui_queue: Queue = Queue()

        registry = load_authorizations(config.AUTHORIZATION_FILE, config.PARKING_CAPACITY)
        payload = {
            "config": {
                "capacity": config.PARKING_CAPACITY,
                "total_vehicles": config.TOTAL_VEHICLES,
                "min_arrival_time": config.MIN_ARRIVAL_TIME,
                "max_arrival_time": config.MAX_ARRIVAL_TIME,
                "min_parking_time": config.MIN_PARKING_TIME,
                "max_parking_time": config.MAX_PARKING_TIME,
            },
            "authorization": {"vehicles": [
                {"plate": item.plate, "authorized": item.authorized, "space_id": item.space_id}
                for item in registry.records.values()
            ]},
            "plate_sequence": list(config.PLATE_SEQUENCE),
        }
        scenario_summaries = list_academic_scenarios()
        scenario_options = {
            scenario.name: (
                scenario.title,
                get_scenario(scenario.name).capacity,
            )
            for scenario in scenario_summaries
        }
        supported_capacities = {
            config.PARKING_CAPACITY,
            *(capacity for _, capacity in scenario_options.values()),
        }
        selected_scenario: dict[str, str | None] = {"name": None}

        def payload_factory() -> dict:
            name = selected_scenario["name"]
            return build_payload(name) if name is not None else payload

        def select_scenario(name: str | None) -> None:
            selected_scenario["name"] = name

        controller = MultiprocessController(
            config.PARKING_CAPACITY,
            audit=audit,
            supported_capacities=supported_capacities,
        )
        simulator = MultiprocessGUIAdapter(controller, ui_queue, payload_factory)
        simulator.start_engine()

        app = ParkingApp(
            event_queue=ui_queue,
            simulator=simulator,
            capacity=config.PARKING_CAPACITY,
            scenario_options=scenario_options,
            on_scenario_selected=select_scenario,
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
                    if not simulator.shutdown_complete:
                        simulator.shutdown_async()
                        if simulator.error is not None:
                            raise simulator.error
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

    if simulator is not None and simulator.metrics is not None:
        print(simulator.metrics.report())


if __name__ == "__main__":
    main()
