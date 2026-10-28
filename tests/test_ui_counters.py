"""Headless tests for UI counter projection from parking events."""

from types import SimpleNamespace
from queue import Queue

from core.events import ParkingEvent
from simulation.metrics import SimulationMetrics
from ui.interface import ParkingApp
from ui.projection import ParkingProjection


class RecordingWidget:
    def __init__(self) -> None:
        self.values: list[int] = []
        self.vehicles: list[int] = []
        self.occupied_slots: list[tuple[int, int]] = []
        self.freed_slots: list[int] = []
        self.messages: list[str] = []

    def update_value(self, value: int) -> None:
        self.values.append(value)

    def add_vehicle(self, vehicle_id: int, plate: str | None = None) -> None:
        if vehicle_id not in self.vehicles:
            self.vehicles.append(vehicle_id)

    def remove_vehicle(self, vehicle_id: int) -> None:
        if vehicle_id in self.vehicles:
            self.vehicles.remove(vehicle_id)

    def occupy_slot(self, space_id: int, vehicle_id: int, plate: str | None = None) -> None:
        self.occupied_slots.append((space_id, vehicle_id))

    def free_slot(self, space_id: int) -> None:
        self.freed_slots.append(space_id)

    def reset(self) -> None:
        self.vehicles.clear()

    def clear(self) -> None:
        self.vehicles.clear()

    def log(self, *args: object) -> None:
        self.messages.append(str(args[1]))


def make_app(capacity: int = 2, on_waiting_time=None) -> ParkingApp:
    app = object.__new__(ParkingApp)
    app.capacity = capacity
    app._closing = False
    app._recovery_used = False
    app._projection_unsafe = False
    app.projection = ParkingProjection(capacity)
    app._ui_metrics = SimulationMetrics()
    app._ui_metrics_active = False
    app._vehicle_plates = {}
    app.occupied_count = 0
    app.waiting_count = 0
    app.total_finished = 0
    app.event_queue = Queue()
    app.card_waiting = RecordingWidget()
    app.card_occupied = RecordingWidget()
    app.card_available = RecordingWidget()
    app.card_finished = RecordingWidget()
    app.card_generated = RecordingWidget()
    app.card_accepted = RecordingWidget()
    app.card_rejected = RecordingWidget()
    app.card_entries = RecordingWidget()
    app.card_cancelled = RecordingWidget()
    app.waiting_lane = RecordingWidget()
    app.parking_grid = RecordingWidget()
    app.event_log = RecordingWidget()
    app.control_bar = SimpleNamespace(set_running=lambda: None, set_pending=lambda *_: None)
    app.simulator = SimpleNamespace(metrics=SimulationMetrics())
    return app


def dispatch(
    app: ParkingApp,
    event_type: str,
    vehicle_id: int,
    space_id: int | None = None,
    waiting_time: float | None = None,
) -> None:
    app._dispatch_event(ParkingEvent(
        type=event_type,
        timestamp=0,
        vehicle_id=vehicle_id,
        space_id=space_id,
        waiting_time=waiting_time,
    ))


def test_entry_only_removes_the_matching_waiting_vehicle() -> None:
    app = make_app()
    dispatch(app, "VEHICLE_WAITING", 1)
    dispatch(app, "VEHICLE_ENTERED", 2, 1)

    assert app.waiting_count == 1
    assert app.waiting_lane.vehicles == [1]


def test_duplicate_waiting_and_entry_events_do_not_inflate_counts() -> None:
    app = make_app()
    dispatch(app, "VEHICLE_WAITING", 1)
    dispatch(app, "VEHICLE_WAITING", 1)
    dispatch(app, "VEHICLE_ENTERED", 1, 1)
    dispatch(app, "VEHICLE_ENTERED", 1, 1)

    assert app.waiting_count == 0
    assert app.occupied_count == 1
    assert app.card_waiting.values == [1, 1, 0, 0]
    assert app.card_occupied.values == [0, 0, 1, 1]


def test_occupancy_cards_share_projection_and_duplicate_events_are_idempotent() -> None:
    app = make_app()
    dispatch(app, "VEHICLE_ENTERED", 1, 1)
    dispatch(app, "VEHICLE_ENTERED", 1, 1)
    assert (app.occupied_count, app.card_available.values[-1]) == (1, 1)

    dispatch(app, "VEHICLE_EXITED", 1, 1)
    dispatch(app, "VEHICLE_EXITED", 1, 1)
    assert (app.occupied_count, app.card_available.values[-1]) == (0, 2)
    assert app.card_occupied.values == [1, 1, 0, 0]


def test_zero_based_core_space_maps_to_first_visible_slot_and_log_number() -> None:
    app = make_app()

    dispatch(app, "VEHICLE_ENTERED", 7, 0)

    assert app.projection.occupied == {1: 7}
    assert app.parking_grid.occupied_slots == [(1, 7)]
    assert "Espacio #1" in app.event_log.messages[-1]
    assert "Espacio #0" not in app.event_log.messages[-1]

    dispatch(app, "VEHICLE_EXITED", 7, 0)

    assert app.projection.occupied == {}
    assert app.parking_grid.freed_slots == [1]
    assert "Espacio #1" in app.event_log.messages[-1]
    assert "Espacio #0" not in app.event_log.messages[-1]


def test_only_entered_events_with_duration_contribute_to_average_wait() -> None:
    app = make_app()

    dispatch(app, "SIMULATION_STARTED", 0)
    dispatch(app, "VEHICLE_WAITING", 1, waiting_time=2.0)
    dispatch(app, "VEHICLE_ENTERED", 1, 0)
    dispatch(app, "VEHICLE_ENTERED", 2, 1, waiting_time=0.0)
    dispatch(app, "VEHICLE_ENTERED", 3, 1, waiting_time=3.5)

    assert app._ui_metrics.snapshot()["average_waiting_time"] == 1.75
