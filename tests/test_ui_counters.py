"""Headless tests for UI counter projection from parking events."""

from types import SimpleNamespace

from ui.interface import ParkingApp


class RecordingWidget:
    def __init__(self) -> None:
        self.values: list[int] = []
        self.vehicles: list[int] = []

    def update_value(self, value: int) -> None:
        self.values.append(value)

    def add_vehicle(self, vehicle_id: int) -> None:
        if vehicle_id not in self.vehicles:
            self.vehicles.append(vehicle_id)

    def remove_vehicle(self, vehicle_id: int) -> None:
        if vehicle_id in self.vehicles:
            self.vehicles.remove(vehicle_id)

    def occupy_slot(self, space_id: int, vehicle_id: int) -> None:
        pass

    def free_slot(self, space_id: int) -> None:
        pass

    def log(self, *args: object) -> None:
        pass


def make_app(capacity: int = 2) -> ParkingApp:
    app = object.__new__(ParkingApp)
    app.capacity = capacity
    app.occupied_count = 0
    app.waiting_count = 0
    app.total_finished = 0
    app._waiting_vehicle_ids = set()
    app._occupied_spaces = {}
    app.card_waiting = RecordingWidget()
    app.card_occupied = RecordingWidget()
    app.card_available = RecordingWidget()
    app.waiting_lane = RecordingWidget()
    app.parking_grid = RecordingWidget()
    app.event_log = RecordingWidget()
    return app


def dispatch(app: ParkingApp, event_type: str, vehicle_id: int, space_id: int | None = None) -> None:
    app._dispatch_event(SimpleNamespace(
        type=event_type,
        timestamp=0,
        vehicle_id=vehicle_id,
        space_id=space_id,
        waiting_time=None,
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
    assert app.card_waiting.values == [1, 0]
    assert app.card_occupied.values == [1]


def test_occupancy_cards_share_projection_and_duplicate_events_are_idempotent() -> None:
    app = make_app()
    dispatch(app, "VEHICLE_ENTERED", 1, 1)
    dispatch(app, "VEHICLE_ENTERED", 1, 1)
    assert (app.occupied_count, app.card_available.values[-1]) == (1, 1)

    dispatch(app, "VEHICLE_EXITED", 1, 1)
    dispatch(app, "VEHICLE_EXITED", 1, 1)
    assert (app.occupied_count, app.card_available.values[-1]) == (0, 2)
    assert app.card_occupied.values == [1, 0]
