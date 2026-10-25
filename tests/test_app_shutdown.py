"""Headless shutdown and restart-boundary checks for the Tk application."""

from collections import deque
from queue import Queue
from types import SimpleNamespace

import pytest

from core.events import ParkingEvent
from simulation import config
from ui.interface import ParkingApp
from ui.projection import ParkingProjection


class FakeRoot:
    def __init__(self) -> None:
        self.callbacks = deque()
        self.destroyed = False
        self.serial = 0

    def after(self, delay, callback):
        assert delay > 0
        self.serial += 1
        self.callbacks.append((delay, callback, self.serial))
        return self.serial

    def after_cancel(self, token):
        self.callbacks = deque(item for item in self.callbacks if item[2] != token)

    def tick(self):
        _, callback, _ = self.callbacks.popleft()
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
    app.card_generated = app.card_accepted = app.card_rejected = app.card_entries = app.card_occupied
    app.card_finished = app.card_cancelled = app.card_occupied
    app.event_log = SimpleNamespace(log=lambda *args: app.logs.append(args))
    app.logs = []
    app.capacity = 5
    app.total_finished = 0
    app._closing = False
    app._shutdown_complete = False
    app._restart_polling = False
    app.poll_interval_ms = 20
    return app


def event(kind):
    return ParkingEvent(kind, 1.0)


def test_close_before_first_run_drains_events_without_stop():
    app = make_app()
    app.event_queue.put(event("VEHICLE_CREATED"))
    app.event_queue.put(event("VEHICLE_CREATED"))
    app._on_close()
    assert app.simulator.stops == 0
    assert app.root.destroyed
    assert app.event_queue.empty()
    assert not app.control_bar.start_enabled
    assert [entry[0] for entry in app.logs] == ["VEHICLE_CREATED", "VEHICLE_CREATED"]


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


def test_failed_run_closes_only_after_adapter_confirms_cleanup():
    simulator = FakeSimulator(active=True, drained=False)
    simulator.error = RuntimeError("transport failed")
    simulator.cleanup_complete = False
    simulator.shutdown_complete = False
    app = make_app(simulator)
    app._on_close()
    app._process_events = lambda: True
    app.root.tick()
    assert not app.root.destroyed
    simulator.cleanup_complete = True
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


def test_start_waits_for_simulation_started_event_before_running():
    app = make_app()
    app.simulator.poll_results = lambda: [("START_ACCEPTED", "run-1", None)]
    app._start_simulation()
    app._process_events()
    assert app.control_bar.status == "INICIANDO"
    assert not app.control_bar.stop_enabled
    app._dispatch_event(event("SIMULATION_STARTED"))
    assert app.control_bar.stop_enabled


def test_pending_restart_poll_does_not_reenable_controls_during_close():
    app = make_app(FakeSimulator(active=True, drained=False))
    app._dispatch_event(event("SIMULATION_FINISHED"))
    app._on_close()
    app.root.tick()
    assert not app.control_bar.start_enabled
    assert not app.root.destroyed


def recovery_app():
    app = make_app(FakeSimulator(active=True, drained=False))
    slots, waiting, cards, errors = {}, {}, {}, []
    app.parking_grid = SimpleNamespace(
        reset=slots.clear,
        occupy_slot=lambda slot, vehicle, plate=None: slots.update({slot: (vehicle, plate)}),
        free_slot=lambda slot: slots.pop(slot, None),
    )
    app.waiting_lane = SimpleNamespace(
        clear=waiting.clear,
        add_vehicle=lambda vehicle, plate: waiting.update({vehicle: plate}),
        remove_vehicle=lambda vehicle: waiting.pop(vehicle, None),
    )
    for name in ('occupied', 'finished', 'generated', 'accepted', 'rejected', 'entries', 'cancelled'):
        setattr(app, f'card_{name}', SimpleNamespace(
            update_value=lambda value, name=name: cards.update({name: value})))
    app.simulator.report_ui_error = errors.append
    return app, slots, waiting, cards, errors


def vehicle_event(kind, vehicle=1, space=None, plate=None):
    return ParkingEvent(kind, 1.0, vehicle_id=vehicle, space_id=space, plate=plate)


def test_partial_dispatch_rebuilds_without_replay_and_poll_survives():
    app, slots, waiting, cards, errors = recovery_app()
    app.control_bar.set_running()
    app.event_queue.put(vehicle_event('VEHICLE_CREATED', plate='REC-001'))
    app.event_queue.put(vehicle_event('VEHICLE_WAITING', plate='REC-001'))
    app.event_queue.put(vehicle_event('VEHICLE_WAITING', 2, plate='REC-002'))
    app._process_events()
    original = app.parking_grid.occupy_slot
    calls = []

    def partial(slot, vehicle, plate=None):
        calls.append(vehicle)
        original(slot, vehicle, plate)
        if len(calls) == 1:
            raise RuntimeError('partial grid update')

    app.parking_grid.occupy_slot = partial
    app.event_queue.put(vehicle_event('VEHICLE_ENTERED', space=0))
    app._schedule_poll()
    assert app.event_queue.empty()
    assert slots == {1: (1, 'REC-001')}
    assert waiting == {2: 'REC-002'}
    assert app.projection.occupied == {1: 1}
    assert app.projection.waiting == {2}
    assert cards['occupied'] == 1
    assert len(errors) == 1 and 'partial grid' in str(errors[0])
    assert len(app.root.callbacks) == 1
    assert app.control_bar.stop_enabled
    assert not any(row[0] == 'VEHICLE_ENTERED' for row in app.logs)
    app.event_queue.put(vehicle_event('VEHICLE_EXITED', space=0))
    app.root.tick()
    assert slots == {} and cards['occupied'] == 0
    assert len(app.root.callbacks) == 1
    app._stop_simulation()
    assert app.simulator.stops == 1
    app._on_close()
    assert app._closing and app.simulator.stops == 2


def test_duplicate_poll_requests_and_reentrancy_have_one_callback():
    app = make_app()
    app._schedule_poll()
    app._schedule_poll()
    assert len(app.root.callbacks) == 1
    app.event_log.log = lambda *args: app._schedule_poll()
    app.event_queue.put(event('VEHICLE_CREATED'))
    app.root.tick()
    assert len(app.root.callbacks) == 1


@pytest.mark.parametrize('producer_active', [False, True])
def test_recovered_finish_still_reenables_start_after_drain(producer_active):
    app, _, _, _, errors = recovery_app()
    app.simulator.active = producer_active
    app.simulator.drained = not producer_active
    pending = app.control_bar.set_pending

    def partial_status(message):
        pending(message)
        if message == 'FINALIZANDO':
            raise RuntimeError('partial finish status')

    app.control_bar.set_pending = partial_status
    app.event_queue.put(event('SIMULATION_FINISHED'))
    app._schedule_poll()
    assert len(errors) == 1 and not app._closing
    app.simulator.active, app.simulator.drained = False, True
    for _ in range(3):
        if app.control_bar.start_enabled:
            break
        app.root.tick()
    assert app.control_bar.start_enabled
    assert sum(callback == app._poll_events for _, callback, _ in app.root.callbacks) == 1


@pytest.mark.parametrize('permanent', [False, True])
def test_repeated_or_unrepairable_render_error_closes_and_drains(permanent):
    app, slots, waiting, cards, errors = recovery_app()
    calls = []

    def broken(*args):
        calls.append(args)
        raise RuntimeError('broken renderer')

    if permanent:
        app.parking_grid.occupy_slot = broken
    else:
        app.event_log.log = broken
    app.event_queue.put(vehicle_event('VEHICLE_ENTERED', space=0, plate='REC-001'))
    app.event_queue.put(vehicle_event('VEHICLE_WAITING', 2, plate='REC-002'))
    for _ in range(140):
        app.event_queue.put(vehicle_event('VEHICLE_CREATED', 3))
    app.event_queue.put(vehicle_event('VEHICLE_EXITED', space=0))
    app.event_queue.put(vehicle_event('VEHICLE_FINISHED'))
    app.event_queue.put(event('SIMULATION_FINISHED'))
    app._schedule_poll()
    assert app._closing and app.simulator.stops == 1
    assert len(calls) == 2
    assert len(errors) == 2
    assert not app.root.destroyed
    app.simulator.active, app.simulator.drained = False, True
    for _ in range(4):
        if app.root.destroyed:
            break
        app.root.tick()
    assert app.root.destroyed and app.event_queue.empty()
    assert app.projection.occupied == {}
    assert app.projection.finished_count == 1
    assert len(calls) == 2  # Fatal drain never revisits the broken widget path.


def test_close_status_failure_cannot_prevent_shutdown_poll():
    app = make_app(FakeSimulator(active=True, drained=False))
    app.control_bar.set_pending = lambda *args: 1 / 0
    app._on_close()
    assert app.simulator.stops == 1
    assert len(app.root.callbacks) == 1
    app.simulator.active, app.simulator.drained = False, True
    app.root.tick()
    assert app.root.destroyed


def test_engine_error_result_preserves_status_and_event_log():
    app = make_app()
    app.simulator.poll_results = lambda: [('ERROR', 'run-1', RuntimeError('engine failed'))]
    app._process_events()
    assert app.control_bar.status == 'ERROR: engine failed'
    assert len(app.logs) == 1 and app.logs[0][:2] == ('ENGINE_ERROR', 'engine failed')


def test_invalid_canonical_fold_fails_closed_without_claiming_event_applied():
    app, slots, waiting, cards, errors = recovery_app()
    app.event_queue.put(vehicle_event('VEHICLE_ENTERED', space=99))
    app.event_queue.put(vehicle_event('VEHICLE_ENTERED', 2, space=0))
    app._schedule_poll()
    assert app._closing and app._projection_unsafe
    assert app.projection.occupied == slots == {}
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert app.event_queue.empty() and app.simulator.stops == 1
    app.simulator.active, app.simulator.drained = False, True
    app.root.tick()
    assert app.root.destroyed


def test_recovery_budget_resets_only_on_new_run_and_reporter_failure_is_bounded(capsys):
    app, slots, waiting, cards, errors = recovery_app()
    logs = app.event_log.log

    def fail_once(kind, *args):
        app.event_log.log = logs
        raise RuntimeError('one-shot log widget failure')

    def failed_reporter(error):
        errors.append(error)
        raise RuntimeError('diagnostic writer failed')

    app.simulator.report_ui_error = failed_reporter
    for run in range(2):
        app.event_queue.put(event('SIMULATION_STARTED'))
        app._process_events()
        app.event_log.log = fail_once
        app.event_queue.put(vehicle_event('VEHICLE_WAITING', plate=f'RUN-{run}'))
        app._process_events()
        assert not app._closing
        assert waiting == {1: f'RUN-{run}'}
        assert app._recovery_used
    assert len(errors) == 2
    assert capsys.readouterr().err.count('RuntimeError: one-shot log widget failure') == 2


def test_adapter_metrics_and_audit_stay_exactly_once_across_ui_recovery(tmp_path):
    from dataclasses import replace
    from simulation.audit_logging import AuditSession
    from simulation.ipc_protocol import parking_event_to_message
    from simulation.metrics import SimulationMetrics
    from ui.multiprocess_adapter import MultiprocessGUIAdapter

    app, slots, waiting, cards, _ = recovery_app()
    messages = Queue()
    audit = AuditSession(tmp_path)
    controller = SimpleNamespace(_audit=audit, get=lambda block=False: messages.get_nowait())
    adapter = MultiprocessGUIAdapter(controller, app.event_queue, lambda: {})
    adapter._run_id = 'recovered-run'
    adapter.metrics = SimulationMetrics()
    adapter._active, adapter._drained = True, False
    app.simulator = adapter
    calls = []
    dispatch = app._dispatch_event

    def dispatch_once(payload):
        calls.append(payload)
        dispatch(payload)

    app._dispatch_event = dispatch_once
    log = app.event_log.log

    def partial_log(kind, *args):
        if kind == 'VEHICLE_ENTERED':
            app.event_log.log = log
            raise RuntimeError('after all stateful widgets updated')
        log(kind, *args)

    app.event_log.log = partial_log
    payloads = [event('SIMULATION_STARTED'),
                replace(vehicle_event('VEHICLE_CREATED', plate='AUD-001'), authorized_space_id=0),
                replace(vehicle_event('VEHICLE_WAITING', plate='AUD-001'), authorized_space_id=0),
                replace(vehicle_event('VEHICLE_ENTERED', space=0, plate='AUD-001'),
                        authorized_space_id=0, waiting_time=0.0)]
    try:
        for seq, payload in enumerate(payloads):
            message = parking_event_to_message(payload, 'recovered-run', seq)
            messages.put(message)
            messages.put(message)  # Existing transport duplicate protection stays intact.
            adapter._drain_one()
            adapter._drain_one()
        before = adapter.metrics.snapshot()
        app._schedule_poll()
        assert calls == payloads and app.event_queue.empty()
        assert adapter.metrics.snapshot() == before
        assert slots == {1: (1, 'AUD-001')} and waiting == {}
        assert cards['generated'] == cards['accepted'] == cards['entries'] == 1
        assert cards['occupied'] == 1 and cards['finished'] == cards['cancelled'] == 0
        assert len(app.root.callbacks) == 1
        assert audit.confirm()
    finally:
        audit.close()
    text = audit.path.read_text(encoding='utf-8')
    assert text.count('record_kind=exception') == 1
    assert 'operation=ui_event_dispatch' in text and 'run_id=recovered-run' in text
    assert 'origin_thread_name=MainThread' in text and 'processName=MainProcess' in text
