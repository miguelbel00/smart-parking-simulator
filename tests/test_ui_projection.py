"""Headless regression checks for core-to-display parking projection."""

from queue import Queue
from types import SimpleNamespace

import pytest

from core.events import ParkingEvent
from core.parking import ParkingSnapshot
from ui.interface import ParkingApp
from ui.projection import ParkingProjection, core_space_to_slot, project_occupied_spaces
from ui.widgets import ParkingLotGridWidget


def event(kind: str, vehicle_id: int | None = None,
          space_id: int | None = None) -> ParkingEvent:
    return ParkingEvent(kind, 1.0, vehicle_id=vehicle_id, space_id=space_id)


class Slot:
    def __init__(self) -> None:
        self.occupied_by = None

    def set_occupied(self, vehicle_id: int) -> None:
        self.occupied_by = vehicle_id

    def set_available(self) -> None:
        self.occupied_by = None

    def reset(self) -> None:
        self.set_available()


class Card:
    def __init__(self) -> None:
        self.value = None

    def update_value(self, value: int) -> None:
        self.value = value


class Lane:
    def __init__(self) -> None:
        self.ids: set[int] = set()

    def add_vehicle(self, vehicle_id: int) -> None:
        self.ids.add(vehicle_id)

    def remove_vehicle(self, vehicle_id: int) -> None:
        self.ids.discard(vehicle_id)

    def clear(self) -> None:
        self.ids.clear()


def make_grid(capacity: int = 5) -> ParkingLotGridWidget:
    grid = ParkingLotGridWidget.__new__(ParkingLotGridWidget)
    grid.slots = {key: Slot() for key in range(1, capacity + 1)}
    return grid


def make_app() -> ParkingApp:
    app = ParkingApp.__new__(ParkingApp)
    app.capacity = 5
    app.projection = ParkingProjection(5)
    app.parking_grid = make_grid()
    app.waiting_lane = Lane()
    app.card_occupied = Card()
    app.card_available = Card()
    app.card_waiting = Card()
    app.event_log = SimpleNamespace(log=lambda *args: None)
    app.control_bar = SimpleNamespace(set_running=lambda: None, set_stopped=lambda: None)
    app.event_queue = Queue()
    return app


def test_mapping_covers_both_ends_and_rejects_invalid_ids() -> None:
    assert core_space_to_slot(0, 5) == 1
    assert core_space_to_slot(4, 5) == 5
    for invalid in (-1, 5):
        with pytest.raises(ValueError):
            core_space_to_slot(invalid, 5)
    with pytest.raises(ValueError):
        project_occupied_spaces(((5, 7),), 5)


def test_projection_events_snapshot_and_counters_agree() -> None:
    projection = ParkingProjection(5)
    projection.apply_event(event("VEHICLE_WAITING", 7))
    assert projection.waiting == {7}
    projection.apply_event(event("VEHICLE_ENTERED", 7, 0))
    projection.apply_event(event("VEHICLE_ENTERED", 8, 2))
    assert projection.occupied == {1: 7, 3: 8}
    assert projection.waiting == set()
    assert projection.occupied_count + projection.available_count == 5

    projection.reconcile_snapshot(ParkingSnapshot(5, 2, 0, ((0, 7), (2, 8))))
    assert projection.occupied == {1: 7, 3: 8}
    projection.apply_event(event("VEHICLE_EXITED", 7, 0))
    assert projection.occupied == {3: 8}
    assert (projection.occupied_count, projection.available_count) == (1, 4)


def test_snapshot_replaces_stale_slots_and_waiters_finish_without_entry() -> None:
    projection = ParkingProjection(5)
    projection.apply_event(event("VEHICLE_ENTERED", 9, 4))
    projection.apply_event(event("VEHICLE_WAITING", 10))
    projection.reconcile_snapshot(ParkingSnapshot(5, 2, 1, ((0, 7), (3, 8))))
    assert projection.occupied == {1: 7, 4: 8}
    assert projection.waiting == {10}
    projection.apply_event(event("VEHICLE_FINISHED", 10))
    projection.apply_event(event("VEHICLE_FINISHED", 10))
    assert projection.waiting == set()
    assert projection.finished_count == 1
    projection.reset()
    assert (projection.occupied, projection.waiting, projection.finished_count) == ({}, set(), 0)


def test_grid_snapshot_adapter_clears_stale_slots_and_rejects_bad_ids() -> None:
    grid = make_grid()
    grid.occupy_slot(5, 9)
    grid.sync_from_snapshot(((0, 7), (3, 8)))
    assert {key: slot.occupied_by for key, slot in grid.slots.items()} == {
        1: 7, 2: None, 3: None, 4: 8, 5: None,
    }
    with pytest.raises(ValueError):
        grid.sync_from_snapshot(((5, 10),))
    assert grid.slots[1].occupied_by == 7


def test_app_reset_precedes_new_events_and_updates_visible_membership() -> None:
    app = make_app()
    app._dispatch_event(event("VEHICLE_WAITING", 7))
    app._dispatch_event(event("VEHICLE_ENTERED", 8, 0))
    app._dispatch_event(event("VEHICLE_FINISHED", 9))
    assert (app.parking_grid.slots[1].occupied_by, app.waiting_lane.ids) == (8, {7})
    assert (app.card_occupied.value, app.card_available.value,
            app.card_waiting.value, app.total_finished) == (1, 4, 1, 1)

    app._dispatch_event(event("SIMULATION_STARTED"))
    assert all(slot.occupied_by is None for slot in app.parking_grid.slots.values())
    assert app.waiting_lane.ids == set()
    assert (app.card_occupied.value, app.card_available.value,
            app.card_waiting.value, app.total_finished) == (0, 5, 0, 0)
    app._dispatch_event(event("VEHICLE_ENTERED", 10, 4))
    assert app.parking_grid.slots[5].occupied_by == 10
    assert app.card_occupied.value + app.card_available.value == 5
    app._dispatch_event(event("VEHICLE_EXITED", 10, 4))
    assert app.parking_grid.slots[5].occupied_by is None
    app._dispatch_event(event("VEHICLE_WAITING", 11))
    app._dispatch_event(event("VEHICLE_FINISHED", 11))
    assert (app.waiting_lane.ids, app.card_waiting.value, app.total_finished) == (set(), 0, 1)


def test_app_snapshot_reconciliation_updates_grid_and_cards_without_guessing_waiters() -> None:
    app = make_app()
    app._dispatch_event(event("VEHICLE_ENTERED", 9, 4))
    app._dispatch_event(event("VEHICLE_WAITING", 10))
    snapshot = ParkingSnapshot(5, 2, 1, ((0, 7), (3, 8)))
    app._reconcile_snapshot(snapshot)
    assert app.projection.occupied == {1: 7, 4: 8}
    assert {key: slot.occupied_by for key, slot in app.parking_grid.slots.items()} == {
        1: 7, 2: None, 3: None, 4: 8, 5: None,
    }
    assert (app.card_occupied.value, app.card_available.value) == (2, 3)
    assert (app.waiting_lane.ids, app.card_waiting.value) == ({10}, 1)


def test_app_invalid_event_space_fails_before_widget_changes() -> None:
    app = make_app()
    with pytest.raises(ValueError):
        app._dispatch_event(event("VEHICLE_ENTERED", 8, 5))
    assert all(slot.occupied_by is None for slot in app.parking_grid.slots.values())


def test_real_queue_consumer_projects_start_enter_exit_in_order() -> None:
    app = make_app()
    for payload in (
        event("SIMULATION_STARTED"),
        event("VEHICLE_ENTERED", 7, 0),
        event("VEHICLE_EXITED", 7, 0),
    ):
        app.event_queue.put(payload)
    app._process_events()
    assert app.event_queue.empty()
    assert app.parking_grid.slots[1].occupied_by is None
    assert (app.card_occupied.value, app.card_available.value) == (0, 5)
