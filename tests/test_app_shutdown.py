"""Headless shutdown and restart-boundary checks for the Tk application."""

from collections import deque
from queue import Queue
from types import SimpleNamespace

from core.events import ParkingEvent
from simulation import config
from ui.interface import ParkingApp
from ui.projection import ParkingProjection


class FakeRoot:
    def __init__(self) -> None:
        self.callbacks = deque()
        self.destroyed = False

    def after(self, delay, callback):
        assert delay > 0
        self.callbacks.append((delay, callback))

    def tick(self):
        _, callback = self.callbacks.popleft()
        callback()

    def destroy(self):
        self.destroyed = True


class FakeSimulator:
    def __init__(self, active=False, drained=True):
        self.active = active
        self.drained = drained
        self.stops = 0
        self.starts = 0

    def is_active(self):
        return self.active

    def is_drained(self):
        return self.drained

    def stop(self):
        self.stops += 1

    def start(self):
        self.starts += 1
        if self.active or not self.drained:
            return False
        self.active = True
        self.drained = False
        return True


class FakeControls:
    def __init__(self):
        self.start_enabled = True
        self.stop_enabled = False
        self.status = ""

    def set_running(self):
        self.start_enabled = False
        self.stop_enabled = True

    def set_stopped(self):
        self.start_enabled = True
        self.stop_enabled = False

    def set_pending(self, message):
        self.start_enabled = False
        self.stop_enabled = False
        self.status = message


def make_app(simulator=None):
    app = ParkingApp.__new__(ParkingApp)
    app.root = FakeRoot()
    app.simulator = simulator or FakeSimulator()
    app.event_queue = Queue()
    app.control_bar = FakeControls()
    app.projection = ParkingProjection(5)
    app.parking_grid = SimpleNamespace(reset=lambda: None)
    app.waiting_lane = SimpleNamespace(clear=lambda: None)
    app.card_occupied = SimpleNamespace(update_value=lambda value: None)
    app.card_available = SimpleNamespace(update_value=lambda value: None)
    app.card_waiting = SimpleNamespace(update_value=lambda value: None)
    app.event_log = SimpleNamespace(log=lambda *args: app.logs.append(args))
    app.logs = []
    app.capacity = 5
    app.total_finished = 0
    app._closing = False
    app._shutdown_complete = False
    app._restart_polling = False
    return app


def event(kind):
    return ParkingEvent(kind, 1.0)


def test_close_before_first_run_drains_events_without_stop():
    app = make_app()
    app.event_queue.put(event("VEHICLE_CREATED"))
    app._on_close()
    assert app.simulator.stops == 0
    assert app.root.destroyed
    assert app.event_queue.empty()
    assert not app.control_bar.start_enabled
    assert app.logs[-1][0] == "VEHICLE_CREATED"


def test_close_after_completed_run_needs_no_stop():
    app = make_app(FakeSimulator(active=False, drained=True))
    app.event_queue.put(event("SIMULATION_FINISHED"))
    app._on_close()
    assert app.simulator.stops == 0
    assert app.root.destroyed
    assert app.event_queue.empty()


def test_active_close_is_idempotent_nonblocking_and_drains_before_destroy():
    simulator = FakeSimulator(active=True, drained=False)
    app = make_app(simulator)
    app._on_close()
    app._on_close()
    assert simulator.stops == 1
    assert not app.control_bar.start_enabled and not app.control_bar.stop_enabled
    assert app.control_bar.status
    assert not app.root.destroyed
    assert app.root.callbacks[0][0] == config.SHUTDOWN_POLL_INTERVAL_MS
    app._start_simulation()
    app._stop_simulation()
    assert (simulator.starts, simulator.stops) == (0, 1)
    app.root.tick()
    assert not app.root.destroyed
    app.event_queue.put(event("SIMULATION_FINISHED"))
    app.root.tick()  # Finish publication does not imply thread exit.
    assert not app.root.destroyed
    assert not app.control_bar.start_enabled
    simulator.active = False
    simulator.drained = True
    app.event_queue.put(event("VEHICLE_FINISHED"))
    app.root.tick()
    assert app.root.destroyed
    assert app.event_queue.empty()
    assert [entry[0] for entry in app.logs[-2:]] == ["SIMULATION_FINISHED", "VEHICLE_FINISHED"]


def test_failed_close_never_destroys_even_after_thread_exit_and_warning(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("ui.interface.time.monotonic", lambda: clock[0])
    simulator = FakeSimulator(active=True, drained=False)
    app = make_app(simulator)
    app._on_close()
    simulator.active = False  # close(wait=True) failed, so drain was never confirmed.
    clock[0] = config.SHUTDOWN_DRAIN_WARNING_SECONDS + 1
    app.root.tick()
    assert not app.root.destroyed
    assert app.root.callbacks
    assert "warning" in app.control_bar.status.lower()
    app.root.tick()
    assert not app.root.destroyed
    simulator.drained = True
    app.root.tick()
    assert app.root.destroyed


def test_warning_never_allows_destroy_while_run_is_active(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("ui.interface.time.monotonic", lambda: clock[0])
    app = make_app(FakeSimulator(active=True, drained=False))
    app._on_close()
    clock[0] = config.SHUTDOWN_DRAIN_WARNING_SECONDS + 1
    for _ in range(3):
        app.root.tick()
        assert not app.root.destroyed
        assert app.root.callbacks


def test_normal_event_poll_keeps_running_while_shutdown_poll_waits():
    app = make_app(FakeSimulator(active=True, drained=False))
    app.poll_interval_ms = 20
    app._schedule_poll()
    app._on_close()
    app.event_queue.put(event("VEHICLE_CREATED"))
    app.root.tick()  # Normal UI consumer is not suspended by shutdown.
    assert app.logs[-1][0] == "VEHICLE_CREATED"
    assert not app.root.destroyed
    app.root.tick()
    assert app.root.callbacks


def test_queue_drain_failure_keeps_window_open_for_retry():
    app = make_app()
    original_queue = app.event_queue
    app.event_queue = SimpleNamespace(get_nowait=lambda: 1 / 0)
    app._on_close()
    assert not app.root.destroyed
    assert "drain failed" in app.control_bar.status.lower()
    app.event_queue = original_queue
    app.root.tick()
    assert app.root.destroyed


def test_finished_event_waits_for_thread_exit_before_enabling_start():
    simulator = FakeSimulator(active=True, drained=True)
    app = make_app(simulator)
    app._dispatch_event(event("SIMULATION_FINISHED"))
    assert not app.control_bar.start_enabled
    app.root.tick()
    assert not app.control_bar.start_enabled
    simulator.active = False
    app.root.tick()
    assert app.control_bar.start_enabled


def test_refused_start_is_visible_and_not_retried():
    simulator = FakeSimulator(active=True)
    app = make_app(simulator)
    app._start_simulation()
    assert simulator.starts == 1
    assert not app.control_bar.start_enabled
    assert any("refused" in entry[1].lower() for entry in app.logs)
    simulator.active = False
    app.root.tick()
    assert simulator.starts == 1
    assert app.control_bar.start_enabled


def test_pending_restart_poll_does_not_reenable_controls_during_close():
    app = make_app(FakeSimulator(active=True, drained=False))
    app._dispatch_event(event("SIMULATION_FINISHED"))
    app._on_close()
    app.root.tick()
    assert not app.control_bar.start_enabled
    assert not app.root.destroyed
