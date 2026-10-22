"""Headless regression checks for core-to-display parking projection."""

from queue import Empty, Queue
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

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

    def set_occupied(self, vehicle_id: int, plate: str | None = None) -> None:
        self.occupied_by = vehicle_id
        self.plate = plate

    def set_available(self) -> None:
        self.occupied_by = None
        self.plate = None

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
    assert app.parking_grid.slots[2].occupied_by == 8
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
    assert (app.parking_grid.slots[1].occupied_by, app.waiting_lane.ids) == (8, {7})
    assert (app.card_occupied.value, app.total_finished) == (1, 1)

    app._dispatch_event(event("SIMULATION_STARTED"))
    assert all(slot.occupied_by is None for slot in app.parking_grid.slots.values())
    assert app.waiting_lane.ids == set()
    assert (app.card_occupied.value, app.total_finished) == (0, 0)
    app._dispatch_event(event("VEHICLE_ENTERED", 10, 4))
    assert app.parking_grid.slots[5].occupied_by == 10
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


def test_parking_app_builds_kpi_cards_with_real_tk() -> None:
    app = ParkingApp(event_queue=Queue())
    try:
        assert app.card_entries.value_color == "#38bdf8"
        assert app.card_finished.value_color == "#38bdf8"
        app._dispatch_event(event("VEHICLE_ENTERED", 34, 0, plate="REAL-34"))
        slot = app.parking_grid.slots[1]
        assert slot.occupied_by == 34
        assert slot.plate == "REAL-34"
        assert slot._lbl_detail.cget("text") == "REAL-34 (#34)"
        assert slot._lbl_id.cget("text") == "Espacio #1"
        app._dispatch_event(event("VEHICLE_EXITED", 34, 0, plate="REAL-34"))
        assert slot.plate is None
        app._dispatch_event(event("VEHICLE_ENTERED", 35, 0))
        assert slot.plate is None
        assert slot._lbl_detail.cget("text") == "Auto #35"
    finally:
        app.root.destroy()
