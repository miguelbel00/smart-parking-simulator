"""Headless regression checks for core-to-display parking projection."""

from queue import Empty, Queue
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
import tkinter as tk

from core.events import ParkingEvent
from core.parking import ParkingLot
from core.parking import ParkingSnapshot
from simulation.authorizations import Authorization, AuthorizationRegistry
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator
from ui.interface import ParkingApp
from ui.projection import ParkingProjection, core_space_to_slot, project_occupied_spaces
from ui.widgets import ParkingLotGridWidget


def event(kind: str, vehicle_id: int | None = None, space_id: int | None = None,
          **details) -> ParkingEvent:
    return ParkingEvent(kind, 1.0, vehicle_id=vehicle_id, space_id=space_id, **details)


class Slot:
    def __init__(self) -> None:
        self.occupied_by = None
        self.plate = None
        self.assigning = None
        self.authorized_plates = ()

    def set_occupied(self, vehicle_id: int, plate: str | None = None) -> None:
        self.occupied_by = vehicle_id
        self.plate = plate

    def set_available(self) -> None:
        self.occupied_by = None
        self.plate = None
        self.assigning = None

    def set_assigning(self, vehicle_id: int, plate: str | None = None) -> None:
        self.assigning = (vehicle_id, plate)
        self.plate = plate

    def set_authorized_plates(self, plates: tuple[str, ...]) -> None:
        self.authorized_plates = plates

    def reset(self) -> None:
        self.set_available()


class Card:
    def __init__(self) -> None:
        self.value = None

    def update_value(self, value: int) -> None:
        self.value = value


class Metrics:
    def __init__(self, **values):
        self.values = values

    def snapshot(self):
        return {"total_generated": 0, "total_admitted": 0, "total_rejected": 0,
                "total_parked": 0, "total_cancelled": 0, **self.values}


class Lane:
    def __init__(self) -> None:
        self.ids: set[int] = set()
        self.plates: dict[int, str] = {}

    def add_vehicle(self, vehicle_id: int, plate: str | None = None) -> None:
        self.ids.add(vehicle_id)
        if plate is not None:
            self.plates[vehicle_id] = plate

    def remove_vehicle(self, vehicle_id: int) -> None:
        self.ids.discard(vehicle_id)
        self.plates.pop(vehicle_id, None)

    def clear(self) -> None:
        self.ids.clear()
        self.plates.clear()


def make_grid(capacity: int = 5) -> ParkingLotGridWidget:
    grid = ParkingLotGridWidget.__new__(ParkingLotGridWidget)
    grid.slots = {key: Slot() for key in range(1, capacity + 1)}
    return grid


def make_app() -> ParkingApp:
    app = ParkingApp.__new__(ParkingApp)
    app._closing = False
    app._shutdown_complete = False
    app._restart_polling = False
    app.capacity = 5
    app._scenario_authorizations = {}
    app._selected_scenario_name = None
    app.projection = ParkingProjection(5)
    app.parking_grid = make_grid()
    app.waiting_lane = Lane()
    app.card_occupied = Card()
    app.card_available = Card()
    app.card_waiting = Card()
    app.card_generated = Card()
    app.card_accepted = Card()
    app.card_rejected = Card()
    app.card_entries = Card()
    app.card_finished = Card()
    app.card_cancelled = Card()
    app.event_log = SimpleNamespace(log=lambda *args: None)
    app.control_bar = SimpleNamespace(set_running=lambda: None, set_stopped=lambda: None,
                                      set_pending=lambda *args: None)
    app.event_queue = Queue()
    app.simulator = SimpleNamespace(metrics=Metrics())
    app.logs = []
    app.event_log = SimpleNamespace(log=lambda *args: app.logs.append(args))
    return app


def make_real_simulator(plates, registry, durations):
    ui_queue = Queue()
    runs = []

    def run_factory():
        metrics = SimulationMetrics()
        forwarding_queue = MetricsForwardingQueue(ui_queue, metrics)
        parking = ParkingLot(1, forwarding_queue, registry)
        runs.append((parking, metrics))
        return parking, forwarding_queue, metrics

    return Simulator(run_factory, plates, duration_factory=iter(durations).__next__), ui_queue, runs


def wait_until(predicate, timeout=3):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        sleep(.002)
    assert predicate()


def drain_events(queue):
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except Empty:
            return events


def registry(**records):
    return AuthorizationRegistry({plate: Authorization(plate, allowed, slot)
                                  for plate, (allowed, slot) in records.items()})


def test_real_engine_same_slot_fifo_projects_waiting_entry_and_metrics(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    first_admitted, release_producer = Event(), Event()
    auth = registry(FIRST=(True, 0), SECOND=(True, 0))
    ui_queue = Queue()
    runs = []

    def run_factory():
        metrics = SimulationMetrics()
        forwarding_queue = MetricsForwardingQueue(ui_queue, metrics)
        parking = ParkingLot(1, forwarding_queue, auth)
        real_admit = parking.admit

        def gated_admit(vehicle):
            result = real_admit(vehicle)
            if vehicle.vehicle_id == 1 and result.accepted:
                first_admitted.set()
                assert release_producer.wait(5)
            return result

        parking.admit = gated_admit
        runs.append((parking, metrics))
        return parking, forwarding_queue, metrics

    simulator = Simulator(run_factory, ("FIRST", "SECOND"),
                          duration_factory=iter((1, .01)).__next__)
    app = make_app()
    app.simulator = simulator
    app.event_queue = ui_queue
    app._closing = True
    started = False
    try:
        assert simulator.start()
        started = True
        wait_until(lambda: bool(runs))
        parking = runs[0][0]
        assert first_admitted.wait(3)
        wait_until(lambda: parking.snapshot().occupied_count == 1)
        release_producer.set()
        wait_until(lambda: parking.snapshot().waiting_count == 1)
        waiting_snapshot = parking.snapshot()
        assert [request.vehicle_id for request in waiting_snapshot.active_requests
                if request.state == "WAITING"] == [2]
        wait_until(simulator.is_drained)

        events = drain_events(ui_queue)
        for item in events:
            ui_queue.put(item)
        app._process_events()

        types = [item.type for item in events]
        waiting_index = types.index("VEHICLE_WAITING")
        assert waiting_index < types.index("VEHICLE_ENTERED", waiting_index)
        entered = [item for item in events if item.type == "VEHICLE_ENTERED"]
        assert [(item.vehicle_id, item.plate, item.space_id) for item in entered] == [
            (1, "FIRST", 0), (2, "SECOND", 0)]
        assert app.parking_grid.slots[1].occupied_by is None
        assert app.projection.finished_count == 2
        assert app.card_entries.value == 2 and app.card_finished.value == 2
        assert events[-1].type == "SIMULATION_FINISHED"
        assert simulator.metrics.snapshot()["total_finished"] == 2
    finally:
        release_producer.set()
        if started and not simulator.is_drained():
            simulator.stop()
            wait_until(simulator.is_drained)
        if started and simulator._thread is not None:
            simulator._thread.join(timeout=5)


def test_real_engine_unauthorized_rejection_reaches_ui_without_active_projection(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    simulator, ui_queue, runs = make_real_simulator(("DENIED",), registry(DENIED=(False, None)), (.01,))
    app = make_app()
    app.simulator = simulator
    app.event_queue = ui_queue
    app._closing = True
    assert simulator.start()
    wait_until(simulator.is_drained)
    events = drain_events(ui_queue)
    for item in events:
        ui_queue.put(item)
    app._process_events()
    rejected = next(item for item in events if item.type == "VEHICLE_REJECTED")
    assert (rejected.plate, rejected.reason, rejected.space_id) == ("DENIED", "NOT_AUTHORIZED", None)
    assert any("DENIED" in entry[1] and "NOT_AUTHORIZED" in entry[1] for entry in app.logs)
    assert app.projection.occupied == {} and app.projection.waiting == set()
    assert app.waiting_lane.ids == set() and app.card_occupied.value == 0
    assert app.card_rejected.value == 1
    assert [item.type for item in events][-1] == "SIMULATION_FINISHED"
    assert simulator.metrics.snapshot()["total_rejected"] == 1


def test_real_engine_stop_cancels_waiter_but_drains_parked_vehicle(monkeypatch):
    from simulation import config
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    admitted_second, release_producer = Event(), Event()
    auth = registry(PARKED=(True, 0), WAITER=(True, 0))
    auth = AuthorizationRegistry({**auth.records, "NEXT": Authorization("NEXT", True, 0)})
    ui_queue = Queue()
    runs = []

    def run_factory():
        metrics = SimulationMetrics()
        forwarding_queue = MetricsForwardingQueue(ui_queue, metrics)
        parking = ParkingLot(1, forwarding_queue, auth)
        real_admit = parking.admit

        def gated_admit(vehicle):
            result = real_admit(vehicle)
            if vehicle.vehicle_id == 2 and result.accepted:
                admitted_second.set()
                assert release_producer.wait(5)
            return result

        parking.admit = gated_admit
        runs.append((parking, metrics))
        return parking, forwarding_queue, metrics

    simulator = Simulator(run_factory, ("PARKED", "WAITER", "NEXT"),
                          duration_factory=iter((2, .01, .01)).__next__)
    app = make_app()
    app.simulator = simulator
    app.event_queue = ui_queue
    app._closing = True
    started = False
    try:
        assert simulator.start()
        started = True
        wait_until(lambda: bool(runs))
        parking = runs[0][0]
        assert admitted_second.wait(3)
        wait_until(lambda: (parking.snapshot().occupied_count == 1
                           and parking.snapshot().waiting_count == 1))

        simulator.stop()
        release_producer.set()
        wait_until(simulator.is_drained)

        events = drain_events(ui_queue)
        for item in events:
            ui_queue.put(item)
        app._process_events()

        waiter_events = [item.type for item in events if item.vehicle_id == 2]
        assert waiter_events == ["VEHICLE_CREATED", "VEHICLE_WAITING", "VEHICLE_CANCELLED"]
        assert sum(item.type == "VEHICLE_CANCELLED" for item in events) == 1
        assert not any(item.vehicle_id == 3 for item in events)
        assert simulator.metrics.snapshot()["total_generated"] == 2
        assert app.projection.waiting == set() and app.waiting_lane.ids == set()
        assert app.projection.occupied == {} and app.card_occupied.value == 0
        assert app.card_cancelled.value == 1 and app.card_finished.value == 1
        finish_index = next(index for index, item in enumerate(events)
                            if item.type == "SIMULATION_FINISHED")
        first_terminals = [index for index, item in enumerate(events)
                           if item.vehicle_id == 1
                           and item.type in ("VEHICLE_EXITED", "VEHICLE_FINISHED")]
        assert len(first_terminals) == 2 and max(first_terminals) < finish_index
        assert [item.type for item in events if item.vehicle_id == 1][-2:] == [
            "VEHICLE_EXITED", "VEHICLE_FINISHED"]
        assert events[-1].type == "SIMULATION_FINISHED"
        assert simulator.metrics.snapshot()["total_cancelled"] == 1
        assert simulator.metrics.snapshot()["total_finished"] == 1
    finally:
        release_producer.set()
        if started and not simulator.is_drained():
            simulator.stop()
            wait_until(simulator.is_drained)
        if started and simulator._thread is not None:
            simulator._thread.join(timeout=5)


def test_rejections_show_plate_reason_refresh_metrics_and_do_not_create_active_state():
    app = make_app()
    app.projection.apply_event(event("VEHICLE_WAITING", 50))
    app.waiting_lane.add_vehicle(50, "WAIT-50")
    app.simulator.metrics = Metrics(total_generated=2, total_admitted=0, total_rejected=2)
    for identity in (1, 2):
        app._dispatch_event(event("VEHICLE_REJECTED", identity, plate="DUP-PLATE",
                                  reason="DUPLICATE_ACTIVE"))
    assert app.card_rejected.value == 2
    assert app.projection.occupied == {}
    assert app.projection.waiting == {50}
    assert app.waiting_lane.ids == {50}
    assert all("DUP-PLATE" in log[1] and "DUPLICATE_ACTIVE" in log[1]
               for log in app.logs)
    assert "#1" in app.logs[0][1] and "#2" in app.logs[1][1]


def test_created_event_alone_refreshes_generated_and_accepted_cards():
    app = make_app()
    app.simulator.metrics = Metrics(total_generated=1, total_admitted=1)
    app._dispatch_event(event("VEHICLE_CREATED", 1, plate="EDU-001", authorized_space_id=0))
    assert (app.card_generated.value, app.card_accepted.value) == (1, 1)


def test_cancellation_removes_only_matching_identity_and_counts_cancellation_only():
    app = make_app()
    for identity in (11, 12):
        app._dispatch_event(event("VEHICLE_WAITING", identity, plate=f"P-{identity}"))
    app.simulator.metrics = Metrics(total_cancelled=1)
    app._dispatch_event(event("VEHICLE_CANCELLED", 11, plate="P-11"))
    assert app.projection.waiting == {12}
    assert app.waiting_lane.ids == {12}
    assert app.card_cancelled.value == 1
    assert app.card_finished.value == 0


def test_wait_entry_exit_and_terminal_cards_keep_plate_and_project_physical_space():
    app = make_app()
    app._dispatch_event(event("VEHICLE_WAITING", 8, plate="CAR-8",
                              authorized_space_id=2))
    assert "CAR-8" in app.logs[-1][1] and "Espacio autorizado #3" in app.logs[-1][1]
    assert app.waiting_lane.plates == {8: "CAR-8"}
    app._dispatch_event(event("VEHICLE_ENTERED", 8, 1, plate="CAR-8"))
    assert app.parking_grid.slots[2].assigning == (8, "CAR-8")
    assert app.parking_grid.slots[2].plate == "CAR-8"
    assert "CAR-8" in app.logs[-1][1] and "Espacio #2" in app.logs[-1][1]
    app._dispatch_event(event("VEHICLE_EXITED", 8, 1, plate="CAR-8"))
    assert app.parking_grid.slots[2].occupied_by is None
    assert app.parking_grid.slots[2].plate is None
    assert "CAR-8" in app.logs[-1][1] and "Espacio #2" in app.logs[-1][1]
    app._dispatch_event(event("VEHICLE_FINISHED", 8, plate="CAR-8"))
    app.simulator.metrics = Metrics(total_cancelled=1)
    app._dispatch_event(event("VEHICLE_CANCELLED", 9, plate="CAR-9"))
    assert app.card_finished.value == 1
    assert app.card_cancelled.value == 1


def test_entry_log_reports_core_waiting_time_and_waiting_log_does_not():
    app = make_app()
    app._dispatch_event(event("VEHICLE_WAITING", 4, plate="W-4", authorized_space_id=0))
    assert "en espera" in app.logs[-1][1] and "espera inicial" not in app.logs[-1][1]
    app._dispatch_event(event("VEHICLE_ENTERED", 4, 0, plate="W-4", waiting_time=2.5))
    assert "tras esperar 2.50s" in app.logs[-1][1]
    app._dispatch_event(event("VEHICLE_ENTERED", 5, 1, plate="W-5"))
    assert "tras esperar" not in app.logs[-1][1]


def test_entered_event_shows_assigning_state_before_occupancy():
    app = make_app()
    app._dispatch_event(event("VEHICLE_ENTERED", 4, 0, plate="W-4"))
    slot = app.parking_grid.slots[1]
    assert slot.assigning == (4, "W-4")
    assert slot.occupied_by is None


def test_grid_renders_authorized_plates_independently_of_occupancy():
    grid = make_grid(capacity=2)
    grid.set_authorizations({1: ("AAA-001", "BBB-002")})
    assert grid.slots[1].authorized_plates == ("AAA-001", "BBB-002")
    assert grid.slots[2].authorized_plates == ()
    grid.occupy_slot(1, 9, "AAA-001")
    assert grid.slots[1].occupied_by == 9
    assert grid.slots[1].authorized_plates == ("AAA-001", "BBB-002")


def test_selected_scenario_authorizations_update_the_grid():
    app = make_app()
    app._scenario_authorizations = {
        "scenario-a": {1: ("AAA-001",)},
        "scenario-b": {2: ("BBB-002",)},
    }
    app._selected_scenario_name = "scenario-b"
    app._apply_selected_authorizations()
    assert app.parking_grid.slots[1].authorized_plates == ()
    assert app.parking_grid.slots[2].authorized_plates == ("BBB-002",)


def test_authorization_card_shows_count_and_popup_plates_without_hiding_occupant():
    app = ParkingApp(event_queue=Queue(), capacity=6)
    try:
        app.parking_grid.set_authorizations({1: ("AAA-001", "BBB-002", "CCC-003")})
        slot = app.parking_grid.slots[1]
        assert slot._lbl_authorized_count.cget("text") == "3 autorizados"
        assert slot._btn_view_plates.cget("text") == "Ver placas"
        assert slot._btn_view_plates.cget("state") == "normal"
        assert slot._lbl_status.cget("text") == "DISPONIBLE"
        assert not hasattr(slot, "_lbl_authorized_icon")

        slot.set_occupied(17, "AAA-001")
        assert slot._lbl_status.cget("text") == "OCUPADO"
        assert slot._lbl_detail.cget("text") == "AAA-001 (#17)"
        assert slot._lbl_authorized_count.cget("text") == "3 autorizados"

        slot._btn_view_plates.invoke()
        popup = slot._plate_window
        assert popup is not None
        try:
            texts = []
            pending = list(popup.winfo_children())
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if widget.winfo_class() == "Label":
                    texts.append(widget.cget("text"))
            assert "Espacio #1" in texts
            assert {"AAA-001", "BBB-002", "CCC-003"}.issubset(texts)
            assert popup.title() == "Autorizados"
        finally:
            popup.destroy()

        empty_slot = app.parking_grid.slots[2]
        assert empty_slot._lbl_authorized_count.cget("text") == "0 autorizados"
        assert empty_slot._btn_view_plates.cget("state") == "disabled"
        assert empty_slot._btn_view_plates.cget("bg") != slot._btn_view_plates.cget("bg")
        empty_slot._btn_view_plates.invoke()
        assert empty_slot._plate_window is None
        assert all(
            app.parking_grid.slots[space_id]._lbl_authorized_count.cget("text")
            == ("3 autorizados" if space_id == 1 else "0 autorizados")
            for space_id in range(1, 7)
        )
    finally:
        app.root.destroy()


def test_six_slot_grid_height_stays_stable_through_run_and_restart():
    app = ParkingApp(event_queue=Queue(), capacity=6)
    try:
        app.root.update_idletasks()
        initial_grid_height = app.parking_grid.winfo_height()
        initial_slot_heights = tuple(
            slot.winfo_height() for slot in app.parking_grid.slots.values()
        )
        assert max(initial_slot_heights) - min(initial_slot_heights) <= 1

        def assert_stable_geometry():
            app.root.update_idletasks()
            assert app.parking_grid.winfo_height() == initial_grid_height
            slots = tuple(app.parking_grid.slots.values())
            assert tuple(slot.winfo_height() for slot in slots) == initial_slot_heights
            assert all(slot.winfo_height() >= slot.winfo_reqheight() for slot in slots)
            assert all(
                slot._btn_view_plates.winfo_rooty() + slot._btn_view_plates.winfo_height()
                <= slot.winfo_rooty() + slot.winfo_height()
                for slot in slots
            )

        app._dispatch_event(event("SIMULATION_STARTED"))
        assert_stable_geometry()
        app._dispatch_event(event("VEHICLE_ENTERED", 1, 0, plate="AAA-001"))
        assert_stable_geometry()
        slot = app.parking_grid.slots[1]
        slot._finish_assignment(slot._assignment_generation, 1, "AAA-001")
        assert_stable_geometry()
        app._dispatch_event(event("VEHICLE_EXITED", 1, 0, plate="AAA-001"))
        assert_stable_geometry()
        app._dispatch_event(event("VEHICLE_FINISHED", 1, plate="AAA-001"))
        app._dispatch_event(event("SIMULATION_FINISHED"))
        assert_stable_geometry()
        app._dispatch_event(event("SIMULATION_STARTED"))
        assert_stable_geometry()
    finally:
        app.root.destroy()


def test_parking_slot_focus_highlights_follow_theme_and_preserve_keyboard_focus():
    from ui.components.theme import COLOR_BORDER, COLOR_INFO, COLOR_OCCUPIED, COLOR_WAITING

    app = ParkingApp(event_queue=Queue(), capacity=6)
    try:
        slot = app.parking_grid.slots[1]
        button = slot._btn_view_plates

        assert slot.cget("highlightcolor") == COLOR_BORDER
        assert button.cget("highlightcolor") == COLOR_INFO
        assert button.cget("takefocus") != "0"

        slot.set_assigning(1, "AAA-001")
        assert slot.cget("highlightbackground") == COLOR_WAITING
        assert slot.cget("highlightcolor") == COLOR_WAITING
        slot.set_occupied(1, "AAA-001")
        assert slot.cget("highlightbackground") == COLOR_OCCUPIED
        assert slot.cget("highlightcolor") == COLOR_OCCUPIED
        slot.set_available()
        assert slot.cget("highlightbackground") == COLOR_BORDER
        assert slot.cget("highlightcolor") == COLOR_BORDER

        app.parking_grid.set_authorizations({1: ("AAA-001",)})
        for _ in range(3):
            button.focus_set()
            app.root.update()
            assert app.root.focus_get() == button
            popup = slot._show_authorized_plates()
            app.root.update()
            assert popup.winfo_exists()
            popup.destroy()
            slot._plate_window = None
            app.root.update()
            assert app.root.focus_get() == button
            assert button.cget("highlightcolor") == COLOR_INFO

            app._dispatch_event(event("SIMULATION_STARTED"))
            app._dispatch_event(event("SIMULATION_FINISHED"))
            app.root.update()
            assert slot.cget("highlightbackground") == COLOR_BORDER
            assert slot.cget("highlightcolor") == COLOR_BORDER
    finally:
        app.root.destroy()


def test_lifecycle_start_clears_visual_residues_and_loads_fresh_run_metrics():
    app = make_app()
    app._dispatch_event(event("VEHICLE_ENTERED", 1, 0, plate="OLD"))
    app._dispatch_event(event("VEHICLE_WAITING", 2, plate="WAIT"))
    app._dispatch_event(event("VEHICLE_CANCELLED", 2, plate="WAIT"))
    app.simulator.metrics = Metrics(total_generated=3, total_admitted=2,
                                    total_rejected=1, total_parked=2, total_cancelled=1)
    app._update_display_counters()
    assert (app.card_generated.value, app.card_accepted.value, app.card_rejected.value,
            app.card_entries.value, app.card_cancelled.value) == (3, 2, 1, 2, 1)
    app.simulator.metrics = Metrics()
    app._dispatch_event(event("SIMULATION_STARTED"))
    assert app.projection.occupied == {} and app.projection.waiting == set()
    assert app.waiting_lane.ids == set()
    assert all(slot.occupied_by is None for slot in app.parking_grid.slots.values())
    assert (app.card_generated.value, app.card_accepted.value, app.card_rejected.value,
            app.card_entries.value, app.card_occupied.value,
            app.card_finished.value, app.card_cancelled.value) == (0, 0, 0, 0, 0, 0, 0)


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


def test_cancelled_removes_only_matching_waiter_and_preserves_occupancy_order():
    projection = ParkingProjection(3)
    projection.apply_event(event("VEHICLE_ENTERED", 1, 0))
    projection.apply_event(event("VEHICLE_WAITING", 2))
    projection.apply_event(event("VEHICLE_WAITING", 3))
    projection.apply_event(event("VEHICLE_CANCELLED", 2))
    assert projection.occupied == {1: 1}
    assert projection.waiting == {3}


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


def test_grid_occupancy_plate_and_legacy_signatures_clear_on_reuse() -> None:
    grid = make_grid(capacity=1)
    slot = grid.slots[1]
    slot.set_occupied(21, "PLATE-21")
    assert (slot.occupied_by, slot.plate) == (21, "PLATE-21")
    slot.set_available()
    assert (slot.occupied_by, slot.plate) == (None, None)

    grid.occupy_slot(1, 22)
    assert (slot.occupied_by, slot.plate) == (22, None)
    grid.free_slot(1)
    grid.occupy_slot(1, 23, "PLATE-23")
    assert (slot.occupied_by, slot.plate) == (23, "PLATE-23")
    grid.reset()
    assert (slot.occupied_by, slot.plate) == (None, None)


def test_app_reset_precedes_new_events_and_updates_visible_membership() -> None:
    app = make_app()
    app._dispatch_event(event("VEHICLE_WAITING", 7))
    app._dispatch_event(event("VEHICLE_ENTERED", 8, 0))
    app._dispatch_event(event("VEHICLE_FINISHED", 9))
    assert (app.parking_grid.slots[1].assigning, app.waiting_lane.ids) == ((8, None), {7})
    assert (app.card_occupied.value, app.total_finished) == (1, 1)

    app._dispatch_event(event("SIMULATION_STARTED"))
    assert all(slot.occupied_by is None for slot in app.parking_grid.slots.values())
    assert app.waiting_lane.ids == set()
    assert (app.card_occupied.value, app.total_finished) == (0, 0)
    app._dispatch_event(event("VEHICLE_ENTERED", 10, 4))
    assert app.parking_grid.slots[5].assigning == (10, None)
    assert app.card_occupied.value == 1
    app._dispatch_event(event("VEHICLE_EXITED", 10, 4))
    assert app.parking_grid.slots[5].occupied_by is None
    app._dispatch_event(event("VEHICLE_WAITING", 11))
    app._dispatch_event(event("VEHICLE_FINISHED", 11))
    assert (app.waiting_lane.ids, app.total_finished) == (set(), 1)


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
    assert app.card_occupied.value == 2
    assert app.waiting_lane.ids == {10}


def test_snapshot_reconciliation_keeps_known_and_snapshot_plates() -> None:
    from core.parking import ActiveRequestSnapshot

    app = make_app()
    app._dispatch_event(event("VEHICLE_ENTERED", 7, 0, plate="KNOWN-7"))
    snapshot = ParkingSnapshot(5, 2, 0, ((0, 7), (3, 8)),
                               (ActiveRequestSnapshot(8, "SNAP-8", 3, "PARKED", 3),))
    app._reconcile_snapshot(snapshot)
    assert app.parking_grid.slots[1].plate == "KNOWN-7"
    assert app.parking_grid.slots[4].plate == "SNAP-8"
    assert app.projection.plates == {7: "KNOWN-7", 8: "SNAP-8"}
    app._dispatch_event(event("VEHICLE_EXITED", 7, 0, plate="KNOWN-7"))
    assert app.projection.plates == {8: "SNAP-8"}


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
    assert app.card_occupied.value == 0


def test_event_log_tag_map_covers_rejected_cancelled_and_error_events() -> None:
    from ui.widgets import EventLogWidget

    assert EventLogWidget.TAG_MAP["VEHICLE_REJECTED"] == "REJECTED"
    assert EventLogWidget.TAG_MAP["VEHICLE_CANCELLED"] == "CANCELLED"
    assert EventLogWidget.TAG_MAP["ENGINE_ERROR"] == "ERROR"
    assert EventLogWidget.TAG_MAP["START_REFUSED"] == "WAITING"


def test_parking_app_builds_kpi_cards_with_real_tk() -> None:
    app = ParkingApp(event_queue=Queue())
    try:
        assert [app.views.tab(tab, "text") for tab in app.views.tabs()] == [
            "Simulación", "Solicitudes", "Telemetría", "Eventos"
        ]
        assert app.views.select() == str(app.simulation_view)
        assert app.parking_grid.master == app.waiting_lane.master
        assert app.parking_grid.master.master == app.simulation_view
        assert len(app.parking_grid.slots) == 6
        assert app.parking_grid.columns == 3
        assert app.parking_grid.master.grid_columnconfigure(0)["weight"] == 1
        assert app.parking_grid.master.grid_columnconfigure(1)["weight"] == 1
        app.root.update_idletasks()
        parking_width = app.parking_grid.winfo_width()
        panel_width = app.waiting_lane.winfo_width()
        assert 49 <= parking_width / (parking_width + panel_width) * 100 <= 51
        top_slot = app.parking_grid.slots[1]
        bottom_slot = app.parking_grid.slots[4]
        assert top_slot.winfo_rooty() == app.waiting_lane.winfo_rooty()
        assert (bottom_slot.winfo_rooty() + bottom_slot.winfo_height()
                == app.waiting_lane.winfo_rooty() + app.waiting_lane.winfo_height())
        assert app.request_table.master == app.requests_view
        assert app.metrics_summary.master == app.telemetry_view
        assert app.event_log.master == app.events_view

        assert app.card_entries.value_color == "#38bdf8"
        assert app.card_finished.value_color == "#38bdf8"
        app._dispatch_event(event("VEHICLE_ENTERED", 34, 0, plate="REAL-34"))
        slot = app.parking_grid.slots[1]
        assert slot._lbl_status.cget("text") == "ASIGNANDO"
        slot._finish_assignment(slot._assignment_generation, 34, "REAL-34")
        assert slot.occupied_by == 34
        assert slot.plate == "REAL-34"
        assert slot._lbl_detail.cget("text") == "REAL-34 (#34)"
        assert slot._lbl_id.cget("text") == "Espacio #1"
        assert app.card_occupied.subtitle == ""
        assert app.card_available.value == "5"
        app._dispatch_event(event("VEHICLE_EXITED", 34, 0, plate="REAL-34"))
        assert slot.plate is None
        assert app.card_available.value == "6"
        app._dispatch_event(event("VEHICLE_ENTERED", 35, 0))
        assert slot.plate is None
        assert slot._lbl_detail.cget("text") == "Auto #35"

        # Switching views is presentation-only and preserves the shared projection.
        for tab in app.views.tabs():
            app.views.select(tab)
            app.root.update_idletasks()
        assert app.projection.occupied == {1: 35}
        slot._finish_assignment(slot._assignment_generation, 35, None)
        assert app.parking_grid.slots[1].occupied_by == 35
    finally:
        app.root.destroy()


def test_scenario_selector_uses_idle_gate_and_resizes_for_selected_run() -> None:
    selected = []

    class Adapter:
        metrics = None

        def __init__(self) -> None:
            self.active = False
            self.drained = True

        def start(self) -> bool:
            self.active = True
            self.drained = False
            return True

        def is_active(self) -> bool:
            return self.active

        def is_drained(self) -> bool:
            return self.drained

    adapter = Adapter()
    app = ParkingApp(
        event_queue=Queue(),
        simulator=adapter,
        capacity=5,
        scenario_options={
            "authorization_rejections": ("Control de acceso", 5),
            "normal_entry_and_exit": ("Multiprocessing e IPC", 1),
        },
        on_scenario_selected=selected.append,
    )
    try:
        assert tuple(app.scenario_selector.cget("values")) == (
            "Control de acceso · 5 puestos",
            "Multiprocessing e IPC · 1 puestos",
        )
        assert app._scenario_var.get() == "Control de acceso · 5 puestos"
        assert selected == ["authorization_rejections"]

        app.scenario_selector.current(1)
        app._handle_scenario_selection()
        assert selected == ["authorization_rejections", "normal_entry_and_exit"]

        app._start_simulation()
        assert str(app.scenario_selector.cget("state")) == "disabled"
        app._consume_event(event("SIMULATION_STARTED"))
        assert app.capacity == 1
        assert len(app.parking_grid.slots) == 1
        assert app.metrics_summary.capacity == 1

        adapter.active = False
        adapter.drained = True
        app._check_restart()
        assert str(app.scenario_selector.cget("state")) == "readonly"
    finally:
        app.root.destroy()


def test_visual_stability_log_cap_scroll_queue_and_telemetry_summary() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        slot = app.parking_grid.slots[1]
        # V1: Slot border thickness, PNG icon dimensions, and label widths stay invariant across states
        assert int(slot.cget("highlightthickness")) == 2
        assert slot._has_icons is True
        assert (slot._img_available.width(), slot._img_available.height()) == (48, 48)
        assert (slot._img_occupied.width(), slot._img_occupied.height()) == (48, 48)
        assert int(slot._lbl_status.cget("width")) == 10
        assert int(slot._lbl_detail.cget("width")) == 13

        # Each view owns the available workspace without resizing hidden views.
        app.views.select(app.events_view)
        app.root.update_idletasks()
        assert app.event_log.winfo_width() >= 380
        app.views.select(app.simulation_view)
        app.root.update_idletasks()
        normal_slot_w, normal_slot_h = slot.winfo_width(), slot.winfo_height()
        slot.set_occupied(1, "EDU-001")
        app.root.update_idletasks()
        assert (slot.winfo_width(), slot.winfo_height()) == (normal_slot_w, normal_slot_h)
        assert str(slot._lbl_icon.cget("image")) == str(slot._img_occupied)
        slot.set_available()
        app.root.update_idletasks()
        assert (slot.winfo_width(), slot.winfo_height()) == (normal_slot_w, normal_slot_h)
        assert str(slot._lbl_icon.cget("image")) == str(slot._img_available)
        app.root.geometry("1920x1080")
        app.root.update_idletasks()
        assert slot.winfo_height() == normal_slot_h

        # V2: WaitingQueueWidget uses scrollable canvas and supports many vehicles
        for vid in range(1, 15):
            app.waiting_lane.add_vehicle(vid, f"EDU-{vid:03d}")
        assert len(app.waiting_lane._vehicles) == 14
        assert app.waiting_lane._canvas.bbox("all") is not None

        # V4: Long error status is truncated visually while preserving full message
        long_err = "ERROR: " + ("x" * 100)
        app.control_bar.set_pending(long_err)
        assert app.control_bar.status_message == long_err
        assert len(app.control_bar._lbl_status.cget("text")) <= app.control_bar.MAX_STATUS_CHARS

        # V7: EventLogWidget caps stored lines at max_lines
        app.event_log.max_lines = 5
        app.event_log.clear()
        for idx in range(12):
            app.event_log.log("VEHICLE_CREATED", f"msg-{idx}", "12:00:00")
        assert app.event_log.line_count == 5
        content = app.event_log._text.get("1.0", "end-1c").splitlines()
        assert len(content) == 5
        assert "msg-11" in content[-1] and "msg-0" not in "\n".join(content)

        # Missing metrics + final report summary panel update on SIMULATION_FINISHED
        metrics = SimulationMetrics()
        metrics.record_generated()
        metrics.record_admitted()
        metrics.record_event(ParkingEvent("SIMULATION_STARTED", 10.0))
        metrics.record_event(ParkingEvent("VEHICLE_WAITING", 10.5, vehicle_id=1))
        metrics.record_event(
            ParkingEvent("VEHICLE_ENTERED", 12.0, vehicle_id=1, space_id=0, waiting_time=1.5)
        )
        metrics.record_event(ParkingEvent("VEHICLE_EXITED", 16.0, vehicle_id=1, space_id=0))
        metrics.record_event(ParkingEvent("VEHICLE_FINISHED", 16.0, vehicle_id=1))
        metrics.record_event(ParkingEvent("SIMULATION_FINISHED", 18.0))
        app.simulator = SimpleNamespace(
            metrics=metrics, is_active=lambda: False, is_drained=lambda: True
        )
        app._dispatch_event(ParkingEvent("SIMULATION_FINISHED", 18.0))

        assert app.metrics_summary._items["avg_wait"].cget("text") == "1.50s"
        assert app.metrics_summary._items["avg_parking"].cget("text") == "4.00s"
        assert app.metrics_summary._items["peak_waiting"].cget("text") == "1"
        assert app.metrics_summary._items["peak_occupancy"].cget("text") == "1 / 5"
        assert app.metrics_summary._items["duration"].cget("text") == "8.00s"
        assert app.metrics_summary._btn_report.cget("state") == "normal"
        assert "Estadísticas finales" in app.metrics_summary._last_report
    finally:
        app.root.destroy()


def test_request_tracking_table_lifecycle_retains_rows_and_uses_em_dash() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        app._dispatch_event(event("SIMULATION_STARTED"))
        # Vehicle 1: full lifecycle CREATED -> WAITING -> ENTERED -> EXITED -> FINISHED
        app._dispatch_event(
            event("VEHICLE_CREATED", 1, plate="EDU-001", authorized_space_id=0)
        )
        rows = dict((r[0], r) for r in app.request_table.rows())
        assert rows["#1"] == (
            "#1", "EDU-001", "Espacio #1", "—", "CREATED", "—", "—"
        )

        app._dispatch_event(
            event("VEHICLE_WAITING", 1, plate="EDU-001", authorized_space_id=0)
        )
        rows = dict((r[0], r) for r in app.request_table.rows())
        assert rows["#1"][4] == "WAITING"

        app._dispatch_event(
            event(
                "VEHICLE_ENTERED",
                1,
                space_id=0,
                plate="EDU-001",
                authorized_space_id=0,
                waiting_time=2.35,
            )
        )
        rows = dict((r[0], r) for r in app.request_table.rows())
        assert rows["#1"] == (
            "#1", "EDU-001", "Espacio #1", "Espacio #1", "ENTERED", "2.35s", "—"
        )

        app._dispatch_event(
            event("VEHICLE_EXITED", 1, space_id=0, plate="EDU-001", authorized_space_id=0)
        )
        rows = dict((r[0], r) for r in app.request_table.rows())
        assert rows["#1"][4] == "EXITED"

        app._dispatch_event(
            event("VEHICLE_FINISHED", 1, plate="EDU-001", authorized_space_id=0)
        )

        # Vehicle 2: REJECTED with reason and missing authorized_space_id
        app._dispatch_event(
            event("VEHICLE_REJECTED", 2, plate="NO-AUTH", reason="NOT_AUTHORIZED")
        )

        # Vehicle 3: CREATED -> WAITING -> CANCELLED with reason
        app._dispatch_event(
            event("VEHICLE_CREATED", 3, plate="EDU-003", authorized_space_id=2)
        )
        app._dispatch_event(
            event("VEHICLE_WAITING", 3, plate="EDU-003", authorized_space_id=2)
        )
        app._dispatch_event(
            event(
                "VEHICLE_CANCELLED",
                3,
                plate="EDU-003",
                authorized_space_id=2,
                reason="STOP_REQUESTED",
            )
        )

        # All rows remain in table for consultation after terminal states
        rows = dict((r[0], r) for r in app.request_table.rows())
        assert set(rows.keys()) == {"#1", "#2", "#3"}
        assert rows["#1"] == (
            "#1", "EDU-001", "Espacio #1", "Espacio #1", "FINISHED", "2.35s", "—"
        )
        assert rows["#2"] == (
            "#2", "NO-AUTH", "—", "—", "REJECTED", "—", "NOT_AUTHORIZED"
        )
        assert rows["#3"] == (
            "#3", "EDU-003", "Espacio #3", "—", "CANCELLED", "—", "STOP_REQUESTED"
        )
    finally:
        app.root.destroy()


def test_pending_requests_grouped_by_authorized_slot_preserve_acceptance_order() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        app._dispatch_event(event("SIMULATION_STARTED"))
        # Vehicle 10 is accepted but has not yet been observed waiting.
        app._dispatch_event(
            event("VEHICLE_CREATED", 10, plate="BBB-010", authorized_space_id=0)
        )
        assert app.waiting_lane.grouped_pending() == {}
        assert app.card_waiting._lbl_value.cget("text") == "0"
        app._dispatch_event(
            event("VEHICLE_WAITING", 10, plate="BBB-010", authorized_space_id=0)
        )

        # A later request for another space is grouped separately without
        # changing the relative order of competing requests for space 1.
        app._dispatch_event(
            event("VEHICLE_CREATED", 7, plate="CCC-007", authorized_space_id=1)
        )
        app._dispatch_event(
            event("VEHICLE_WAITING", 7, plate="CCC-007", authorized_space_id=1)
        )

        # Vehicle 2 waits at the same slot; acceptance order is preserved.
        app._dispatch_event(
            event("VEHICLE_CREATED", 2, plate="DDD-002", authorized_space_id=0)
        )
        app._dispatch_event(
            event("VEHICLE_WAITING", 2, plate="DDD-002", authorized_space_id=0)
        )
        # Vehicle 5 is created for a free slot, so it is not shown as waiting.
        app._dispatch_event(
            event("VEHICLE_CREATED", 5, plate="EEE-005", authorized_space_id=1)
        )

        grouped = app.waiting_lane.grouped_pending()
        assert grouped == {1: [10, 2], 2: [7]}
        assert app.waiting_lane._plates[10] == "BBB-010"
        assert app.waiting_lane._plates[2] == "DDD-002"
        assert app.waiting_lane._states[2] == "WAITING"
        assert app.card_waiting._lbl_value.cget("text") == "3"
        assert app.waiting_lane._lbl_count.cget("text") == "3 pendientes"

        group_row = app.waiting_lane._group_rows[1][0]
        assert app.waiting_lane._group_rows[1][0] is group_row
        assert len(app.waiting_lane._items_container.winfo_children()) == 3
        assert app.waiting_lane._group_rows[1][2].cget("text") == "2 en espera"
        assert [label.cget("text") for label in app.waiting_lane._group_rows[1][4].values()] == [
            "BBB-010", "DDD-002"
        ]
        assert app.waiting_lane._lbl_title.cget("text") == "Solicitudes pendientes"
        assert app.waiting_lane._lbl_subtitle.cget("text") == "FIFO por espacio autorizado"
        assert app.waiting_lane._group_rows[1][4][10].cget("bg") == "#78350f"

        for vehicle_id in range(11, 31):
            app._dispatch_event(
                event("VEHICLE_CREATED", vehicle_id, plate=f"Q-{vehicle_id}",
                      authorized_space_id=0)
            )
            app._dispatch_event(
                event("VEHICLE_WAITING", vehicle_id, plate=f"Q-{vehicle_id}",
                      authorized_space_id=0)
            )
        assert len(app.waiting_lane._group_rows) == 2
        assert app.waiting_lane._group_rows[1][0] is group_row
        assert len(app.waiting_lane._items_container.winfo_children()) == 3
        assert app.waiting_lane._group_rows[1][2].cget("text") == "22 en espera"
        assert app.waiting_lane._lbl_count.cget("text") == "23 pendientes"
        assert list(app.waiting_lane._group_rows[1][4]) == [10, 2, *range(11, 31)]
        assert len(app.waiting_lane._group_rows[1][4]) == 22
        app.root.update_idletasks()
        assert app.waiting_lane._canvas.cget("scrollregion")
        assert app.waiting_lane._scrollbar.winfo_ismapped()
        large_scroll_region = app.waiting_lane._canvas.cget("scrollregion")

        # When vehicle 10 enters, it leaves the head of Puesto #1's queue.
        app._dispatch_event(
            event(
                "VEHICLE_ENTERED",
                10,
                space_id=0,
                plate="BBB-010",
                authorized_space_id=0,
                waiting_time=0.5,
            )
        )
        assert app.waiting_lane.grouped_pending() == {1: [2, *range(11, 31)], 2: [7]}
        assert app.waiting_lane._group_rows[1][0] is group_row
        assert len(app.waiting_lane._items_container.winfo_children()) == 3
        assert list(app.waiting_lane._group_rows[1][4]) == [2, *range(11, 31)]
        assert app.waiting_lane._group_rows[1][4][2].cget("bg") == "#78350f"

        # Cancelling vehicle 5, which was never waiting, leaves the view unchanged.
        app._dispatch_event(
            event(
                "VEHICLE_CANCELLED",
                5,
                plate="EEE-005",
                authorized_space_id=1,
                reason="STOP_REQUESTED",
            )
        )
        assert app.waiting_lane.grouped_pending() == {1: [2, *range(11, 31)], 2: [7]}
        assert app.card_waiting._lbl_value.cget("text") == "22"
        app._dispatch_event(
            event("VEHICLE_CANCELLED", 7, plate="CCC-007", authorized_space_id=1,
                  reason="STOP_REQUESTED")
        )
        assert app.waiting_lane.grouped_pending() == {1: [2, *range(11, 31)]}
        assert app.waiting_lane._group_rows[2][0].winfo_manager() == ""
        assert app.waiting_lane._lbl_count.cget("text") == "21 pendientes"
        for vehicle_id in [2, *range(11, 31)]:
            app._dispatch_event(event(
                "VEHICLE_CANCELLED", vehicle_id, plate=f"Q-{vehicle_id}",
                authorized_space_id=0, reason="STOP_REQUESTED",
            ))
        app.root.update_idletasks()
        assert app.waiting_lane._lbl_count.cget("text") == "0 pendientes"
        assert app.waiting_lane._group_rows[1][4] == {}
        assert not app.waiting_lane._scrollbar.winfo_ismapped()
        assert app.waiting_lane._canvas.cget("scrollregion") != large_scroll_region

        # A single unusually long valid plate still requires horizontal scrolling.
        long_plate = "PLATE" * 24
        app._dispatch_event(event(
            "VEHICLE_CREATED", 99, plate=long_plate, authorized_space_id=0,
        ))
        app._dispatch_event(event(
            "VEHICLE_WAITING", 99, plate=long_plate, authorized_space_id=0,
        ))
        app.root.update_idletasks()
        assert app.waiting_lane._scrollbar.winfo_ismapped()
        assert app.waiting_lane._canvas.bbox("all")[2] > app.waiting_lane._canvas.winfo_width()
    finally:
        app.root.destroy()


def test_waiting_queue_updates_chips_incrementally_and_uniformly(monkeypatch) -> None:
    app = ParkingApp(event_queue=Queue(), capacity=3)
    try:
        app._dispatch_event(event("SIMULATION_STARTED"))
        for vehicle_id, plate, space_id in (
            (1, "A", 0),
            (2, "LONG-PLATE-12345678901234567890", 0),
            (3, "B", 1),
        ):
            app._dispatch_event(event(
                "VEHICLE_CREATED", vehicle_id, plate=plate,
                authorized_space_id=space_id,
            ))
            app._dispatch_event(event(
                "VEHICLE_WAITING", vehicle_id, plate=plate,
                authorized_space_id=space_id,
            ))

        lane = app.waiting_lane
        group_one = lane._group_rows[1]
        group_two = lane._group_rows[2]
        first_chip = group_one[4][1]
        long_chip = group_one[4][2]
        unaffected_chip = group_two[4][3]
        app.root.update_idletasks()

        assert first_chip.winfo_reqwidth() == unaffected_chip.winfo_reqwidth()
        assert long_chip.winfo_reqwidth() > first_chip.winfo_reqwidth()
        assert first_chip.winfo_reqheight() == long_chip.winfo_reqheight()
        assert first_chip.cget("font") == long_chip.cget("font")
        assert first_chip.cget("text") == "A"
        assert long_chip.cget("text") == "LONG-PLATE-12345678901234567890"
        assert first_chip.cget("bg") != long_chip.cget("bg")
        normal_background = long_chip.cget("bg")
        unaffected_geometry = (
            unaffected_chip.winfo_reqwidth(), unaffected_chip.winfo_reqheight()
        )

        forgotten_chips = []
        original_pack_forget = tk.Pack.pack_forget

        def record_pack_forget(widget):
            if widget in {first_chip, long_chip, unaffected_chip}:
                forgotten_chips.append(widget)
            return original_pack_forget(widget)

        monkeypatch.setattr(tk.Pack, "pack_forget", record_pack_forget)

        # A short append to space 1 must not unmap/repack chips in either group.
        app._dispatch_event(event("VEHICLE_CREATED", 4, plate="C", authorized_space_id=0))
        app._dispatch_event(event("VEHICLE_WAITING", 4, plate="C", authorized_space_id=0))
        assert not forgotten_chips
        assert lane._group_rows[1][4][1] is first_chip
        assert lane._group_rows[1][4][2] is long_chip
        assert lane._group_rows[2][4][3] is unaffected_chip
        assert (unaffected_chip.winfo_reqwidth(), unaffected_chip.winfo_reqheight()) == unaffected_geometry
        assert list(lane._group_rows[1][4]) == [1, 2, 4]
        assert lane._group_rows[1][2].cget("text") == "3 en espera"

        # Removing the FIFO head promotes, but does not recreate, the next chip.
        app._dispatch_event(event(
            "VEHICLE_ENTERED", 1, space_id=0, plate="A", authorized_space_id=0,
        ))
        assert list(lane._group_rows[1][4]) == [2, 4]
        assert lane._group_rows[1][4][2] is long_chip
        assert long_chip.cget("bg") != normal_background

        # Remove an intermediate request, then the tail; retain the other chip.
        app._dispatch_event(event(
            "VEHICLE_CREATED", 5, plate="D", authorized_space_id=0,
        ))
        app._dispatch_event(event(
            "VEHICLE_WAITING", 5, plate="D", authorized_space_id=0,
        ))
        tail_chip = lane._group_rows[1][4][5]
        app._dispatch_event(event(
            "VEHICLE_CANCELLED", 4, plate="C", authorized_space_id=0,
            reason="STOP_REQUESTED",
        ))
        assert list(lane._group_rows[1][4]) == [2, 5]
        assert lane._group_rows[1][4][5] is tail_chip
        app._dispatch_event(event(
            "VEHICLE_CANCELLED", 5, plate="D", authorized_space_id=0,
            reason="STOP_REQUESTED",
        ))
        assert list(lane._group_rows[1][4]) == [2]
        assert lane._group_rows[1][4][2] is long_chip
        assert lane._group_rows[1][2].cget("text") == "1 en espera"
        assert lane._lbl_count.cget("text") == "2 pendientes"
        assert not forgotten_chips
    finally:
        app.root.destroy()


def test_waiting_queue_sizes_exceptional_chips_without_resizing_existing_groups() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=3)
    try:
        app._dispatch_event(event("SIMULATION_STARTED"))
        for vehicle_id, plate, space_id in (
            (1, "PIA-160", 0),
            (2, "IPZ-354", 1),
        ):
            app._dispatch_event(event(
                "VEHICLE_CREATED", vehicle_id, plate=plate,
                authorized_space_id=space_id,
            ))
            app._dispatch_event(event(
                "VEHICLE_WAITING", vehicle_id, plate=plate,
                authorized_space_id=space_id,
            ))

        lane = app.waiting_lane
        first_chip = lane._group_rows[1][4][1]
        second_chip = lane._group_rows[2][4][2]
        app.root.update_idletasks()
        common_dimensions = (first_chip.winfo_reqwidth(), first_chip.winfo_reqheight())
        assert (second_chip.winfo_reqwidth(), second_chip.winfo_reqheight()) == common_dimensions

        # Adding the third scenario plate may not resize the first two chips,
        # even though they belong to different authorized spaces.
        app._dispatch_event(event("VEHICLE_CREATED", 3, plate="HVG-983", authorized_space_id=2))
        app._dispatch_event(event("VEHICLE_WAITING", 3, plate="HVG-983", authorized_space_id=2))
        app.root.update_idletasks()
        third_chip = lane._group_rows[3][4][3]
        assert first_chip is lane._group_rows[1][4][1]
        assert second_chip is lane._group_rows[2][4][2]
        assert (first_chip.winfo_reqwidth(), first_chip.winfo_reqheight()) == common_dimensions
        assert (second_chip.winfo_reqwidth(), second_chip.winfo_reqheight()) == common_dimensions
        assert (third_chip.winfo_reqwidth(), third_chip.winfo_reqheight()) == common_dimensions
        assert first_chip.cget("width") == second_chip.cget("width") == third_chip.cget("width")

        before_long_plate = {
            chip: (chip.winfo_reqwidth(), chip.winfo_reqheight(), chip.winfo_geometry())
            for chip in (first_chip, second_chip, third_chip)
        }
        exceptional_plate = "X" * 60
        app._dispatch_event(event(
            "VEHICLE_CREATED", 4, plate=exceptional_plate, authorized_space_id=2,
        ))
        app._dispatch_event(event(
            "VEHICLE_WAITING", 4, plate=exceptional_plate, authorized_space_id=2,
        ))
        app.root.update_idletasks()
        exceptional_chip = lane._group_rows[3][4][4]
        exceptional_background = exceptional_chip.cget("bg")
        assert exceptional_chip.cget("text") == exceptional_plate
        assert exceptional_chip.winfo_reqwidth() > common_dimensions[0]
        assert all(
            (chip.winfo_reqwidth(), chip.winfo_reqheight(), chip.winfo_geometry()) == dimensions
            for chip, dimensions in before_long_plate.items()
        )
        assert lane._scrollbar.winfo_ismapped()

        # FIFO removal still promotes the next chip without changing its size.
        app._dispatch_event(event(
            "VEHICLE_ENTERED", 3, plate="HVG-983", space_id=2,
            authorized_space_id=2,
        ))
        app.root.update_idletasks()
        assert lane.grouped_pending()[3] == [4]
        assert exceptional_chip is lane._group_rows[3][4][4]
        assert exceptional_chip.cget("bg") != exceptional_background
        assert lane._lbl_count.cget("text") == "3 pendientes"
    finally:
        app.root.destroy()


def test_metrics_coherence_under_backlog_and_control_bar_states() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        # Simulate adapter/engine metrics already ahead due to unprocessed queue backlog
        ahead_metrics = SimulationMetrics()
        for vid in range(1, 6):
            ahead_metrics.record_generated()
            ahead_metrics.record_admitted()
            ahead_metrics.record_event(
                event(
                    "VEHICLE_ENTERED",
                    vid,
                    space_id=0,
                    plate=f"EDU-{vid:03d}",
                    authorized_space_id=0,
                    waiting_time=1.0,
                )
            )
        app.simulator = SimpleNamespace(
            metrics=ahead_metrics,
            is_active=lambda: True,
            is_drained=lambda: False,
            stop=lambda: None,
        )

        app._dispatch_event(event("SIMULATION_STARTED"))
        # Only 1 vehicle event has been processed by the UI so far
        app._dispatch_event(
            event("VEHICLE_CREATED", 1, plate="EDU-001", authorized_space_id=0)
        )
        app._dispatch_event(
            event(
                "VEHICLE_ENTERED",
                1,
                space_id=0,
                plate="EDU-001",
                authorized_space_id=0,
                waiting_time=1.25,
            )
        )

        # UI cards must reflect the 1 processed event, NOT the 5 buffered in ahead_metrics
        assert app.card_generated._lbl_value.cget("text") == "1"
        assert app.card_accepted._lbl_value.cget("text") == "1"
        assert app.card_entries._lbl_value.cget("text") == "1"
        assert app.card_occupied._lbl_value.cget("text") == "1"
        assert app.card_available._lbl_value.cget("text") == "4"
        assert app.card_peak_occupancy._lbl_value.cget("text") == "1"
        assert app.card_avg_wait._lbl_value.cget("text") == "1.25s"

        # ControlBar transitions: INICIANDO -> EN EJECUCIÓN -> DETENCIÓN SOLICITADA -> FINALIZANDO -> FINALIZADA -> ERROR
        app.control_bar.set_pending("INICIANDO")
        assert app.control_bar.status_message == "INICIANDO"
        assert app.control_bar._btn_start.cget("state") == "disabled"
        assert app.control_bar._btn_stop.cget("state") == "disabled"

        app.control_bar.set_running()
        assert app.control_bar.status_message == "EN EJECUCIÓN"
        assert app.control_bar._btn_start.cget("state") == "disabled"
        assert app.control_bar._btn_stop.cget("state") == "normal"

        app._stop_simulation()
        assert app.control_bar.status_message == "DETENCIÓN SOLICITADA"
        assert app.control_bar._btn_stop.cget("state") == "disabled"

        app.control_bar.set_pending("FINALIZANDO")
        assert app.control_bar.status_message == "FINALIZANDO"

        app.control_bar.set_stopped()
        assert app.control_bar.status_message == "FINALIZADA"
        assert app.control_bar._btn_start.cget("state") == "normal"

        app.control_bar.set_pending("ERROR: Fallo IPC")
        assert app.control_bar.status_message == "ERROR: Fallo IPC"
    finally:
        app.root.destroy()


def test_event_log_filters_preserve_records_and_clear_view_note() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        assert app.event_log._btn_clear.cget("text") == "Limpiar vista"
        assert "no modifica la auditoría persistida" in app.event_log._lbl_audit_note.cget("text")

        app._dispatch_event(event("SIMULATION_STARTED"))
        app._dispatch_event(
            event("VEHICLE_CREATED", 1, plate="ABC-111", authorized_space_id=0)
        )
        app._dispatch_event(
            event(
                "VEHICLE_ENTERED",
                1,
                space_id=0,
                plate="ABC-111",
                authorized_space_id=0,
                waiting_time=1.75,
            )
        )
        app._dispatch_event(
            event("VEHICLE_REJECTED", 2, plate="XYZ-999", reason="NOT_AUTHORIZED")
        )

        all_lines = app.event_log.visible_lines()
        assert len(all_lines) == 4
        assert any("tras esperar 1.75s" in line for line in all_lines)

        # Filter by plate
        app.event_log.set_filters(plate="XYZ")
        filtered_plate = app.event_log.visible_lines()
        assert len(filtered_plate) == 1
        assert "XYZ-999" in filtered_plate[0]

        # Filter by request ID
        app.event_log.set_filters(vehicle_id="1", plate="", event_type="TODOS")
        filtered_id = app.event_log.visible_lines()
        assert len(filtered_id) == 2
        assert all("ABC-111" in line for line in filtered_id)

        # Filter by event type
        app.event_log.set_filters(vehicle_id="", plate="", event_type="VEHICLE_ENTERED")
        filtered_type = app.event_log.visible_lines()
        assert len(filtered_type) == 1
        assert "tras esperar 1.75s" in filtered_type[0]

        # Resetting filters restores all lines without altering metrics or projection
        app.event_log.reset_filters()
        assert len(app.event_log.visible_lines()) == 4
        assert app.card_accepted._lbl_value.cget("text") == "1"
        assert app.card_rejected._lbl_value.cget("text") == "1"
    finally:
        app.root.destroy()


def test_persistent_summary_warning_architecture_footer_and_canonical_recovery() -> None:
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        assert (
            app._lbl_arch_info.cget("text")
            == "Arquitectura: Motor hijo → IPC → adaptador del proceso padre → cola local → Tkinter"
        )

        app._dispatch_event(event("SIMULATION_STARTED"))
        app._dispatch_event(
            event("VEHICLE_CREATED", 1, plate="EDU-001", authorized_space_id=0)
        )

        # Inject transient failure in parking_grid.assign_slot during VEHICLE_ENTERED
        original_assign = app.parking_grid.assign_slot
        calls = {"count": 0}

        def flaky_assign(slot_id: int, vehicle_id: int, plate: str | None = None) -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("Fallo visual transitorio simulado")
            original_assign(slot_id, vehicle_id, plate)

        app.parking_grid.assign_slot = flaky_assign
        app._dispatch_event(
            event(
                "VEHICLE_ENTERED",
                1,
                space_id=0,
                plate="EDU-001",
                authorized_space_id=0,
                waiting_time=0.8,
            )
        )
        app.parking_grid.assign_slot = original_assign

        # Canonical recovery reconstructed grid, table, and metrics without duplicating state
        assert app.parking_grid.slots[1].occupied_by == 1
        assert app.parking_grid.slots[1].plate == "EDU-001"
        assert len(app.request_table.rows()) == 1
        assert app.card_entries._lbl_value.cget("text") == "1"

        # Engine error triggers incomplete execution/audit warning on persistent summary
        app._dispatch_event(
            event("ENGINE_ERROR", reason="Child process exited unexpectedly")
        )
        assert "Advertencia" in app.metrics_summary.warning_message
    finally:
        app.root.destroy()


def test_real_tkinter_mainloop_with_multiprocess_ipc_lifecycle() -> None:
    from simulation.multiprocess import MultiprocessController
    from ui.multiprocess_adapter import MultiprocessGUIAdapter

    event_queue: Queue = Queue()
    state = {
        "run_index": 0,
        "start_accepted": False,
        "lifecycle_watchdog_scheduled": False,
        "stopped_first": False,
        "restarted": False,
        "completed_second": False,
    }

    def make_payload() -> dict:
        state["run_index"] += 1
        if state["run_index"] == 1:
            # First run stays active long enough for an early STOP command to be accepted by the child engine
            return {
                "config": {
                    "capacity": 5,
                    "total_vehicles": 6,
                    "min_arrival_time": 0,
                    "max_arrival_time": 1,
                    "min_parking_time": 1,
                    "max_parking_time": 1,
                },
                "authorization": {
                    "vehicles": [
                        {"plate": f"EDU-00{i}", "authorized": True, "space_id": (i - 1) % 5}
                        for i in range(1, 7)
                    ]
                },
                "plate_sequence": [f"EDU-00{i}" for i in range(1, 7)],
            }
        # Second run completes quickly on its own (0s arrival and 0s parking integers)
        return {
            "config": {
                "capacity": 5,
                "total_vehicles": 3,
                "min_arrival_time": 0,
                "max_arrival_time": 0,
                "min_parking_time": 0,
                "max_parking_time": 0,
            },
            "authorization": {
                "vehicles": [
                    {"plate": f"EDU-00{i}", "authorized": True, "space_id": (i - 1) % 5}
                    for i in range(1, 4)
                ]
            },
            "plate_sequence": [f"EDU-00{i}" for i in range(1, 4)],
        }

    controller = MultiprocessController(5)
    adapter = MultiprocessGUIAdapter(controller, event_queue, make_payload)
    adapter.start_engine()
    app = ParkingApp(event_queue=event_queue, simulator=adapter, capacity=5)
    original_poll_results = adapter.poll_results

    def poll_results_and_watch_start(*args, **kwargs):
        results = original_poll_results(*args, **kwargs)
        if any(name == "START_ACCEPTED" for name, _, _ in results):
            state["start_accepted"] = True
            if not state["lifecycle_watchdog_scheduled"]:
                state["lifecycle_watchdog_scheduled"] = True
                app.root.after(30000, app._on_close)
        return results

    adapter.poll_results = poll_results_and_watch_start

    try:
        # Step 1: Start simulation inside real Tkinter event loop
        app.root.after(40, app._start_simulation)

        # Stop in response to the first real request instead of polling a
        # transient status label that may be skipped under a busy test suite.
        def request_early_stop() -> None:
            if state["stopped_first"]:
                return
            state["stopped_first"] = True
            app._stop_simulation()

        original_dispatch = app._dispatch_event

        def dispatch_and_stop_after_creation(event):
            original_dispatch(event)
            if not state["stopped_first"] and event.type == "VEHICLE_CREATED":
                app.root.after_idle(request_early_stop)

        app._dispatch_event = dispatch_and_stop_after_creation

        # Step 3: Wait until first run finishes & drains, then trigger a restart and let it finish
        def monitor_lifecycle() -> None:
            if (
                state["stopped_first"]
                and not state["restarted"]
                and not adapter.is_active()
                and app.control_bar.status_message == "FINALIZADA"
                and adapter.is_drained()
            ):
                state["restarted"] = True
                app._start_simulation()
                app.root.after(60, monitor_lifecycle)
                return
            if (
                state["restarted"]
                and not adapter.is_active()
                and app.control_bar.status_message == "FINALIZADA"
                and adapter.is_drained()
            ):
                state["completed_second"] = True
                app._on_close()
                return
            app.root.after(60, monitor_lifecycle)

        app.root.after(150, monitor_lifecycle)
        # Bound engine startup separately from the lifecycle watchdog, which starts
        # only after the transport confirms that START was accepted.
        app.root.after(60000, app._on_close)
        app.run()

        diagnostics = (
            f"state={state}, active={adapter.is_active()}, drained={adapter.is_drained()}, "
            f"error={adapter.error!r}, transport_alive={adapter._thread.is_alive()}, "
            f"engine_exitcode={controller._process.exitcode}, "
            f"ui_queue_size={event_queue.qsize()}, status={app.control_bar.status_message!r}"
        )
        assert state["stopped_first"], f"first request was not observed; {diagnostics}"
        assert state["restarted"], f"first run did not restart; {diagnostics}"
        assert state["completed_second"], f"second run did not complete; {diagnostics}"
        assert adapter.is_drained() is True
    finally:
        if not adapter.shutdown_complete:
            adapter.shutdown_async()
        try:
            app.root.destroy()
        except Exception:
            pass
