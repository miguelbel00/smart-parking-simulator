from queue import Empty, Queue
from threading import Event
from time import monotonic, sleep

from core.events import ParkingEvent
from simulation.audit_logging import AuditSession
from simulation.ipc_protocol import parking_event_to_message
from simulation.metrics import SimulationMetrics
from simulation.multiprocess import MultiprocessController
from ui.multiprocess_adapter import MultiprocessGUIAdapter


class FakeController:
    def __init__(self):
        self.messages = Queue()
        self.stop_entered = Event()
        self.release_stop = Event()

    def start_engine(self):
        pass

    def get(self, block=False):
        return self.messages.get_nowait()

    def stop(self, run_id):
        self.stop_entered.set()
        self.release_stop.wait(1)


def test_ipc_event_translates_once_and_updates_current_run_metrics():
    controller = FakeController()
    destination = Queue()
    adapter = MultiprocessGUIAdapter(controller, destination, lambda: {})
    adapter._run_id = "run-test"
    adapter.metrics = SimulationMetrics()
    event = ParkingEvent("VEHICLE_CREATED", 10.0, vehicle_id=1, plate="EDU-001",
                         authorized_space_id=0)
    controller.messages.put(parking_event_to_message(event, "run-test", 0))

    adapter._drain_one()

    assert destination.get_nowait() == event
    snapshot = adapter.metrics.snapshot()
    assert snapshot["total_generated"] == snapshot["total_admitted"] == 1
    assert destination.empty()


def test_stop_request_does_not_wait_for_controller_reply():
    controller = FakeController()
    adapter = MultiprocessGUIAdapter(controller, Queue(), lambda: {})
    adapter._run_id = "run-test"
    adapter._active = True
    adapter.start_engine()
    try:
        deadline = monotonic() + 1
        while not adapter._started and monotonic() < deadline:
            pass
        adapter.stop()
        assert controller.stop_entered.wait(1)
    finally:
        controller.release_stop.set()
        adapter._stopping = True
        adapter._drained = True
        # Avoid invoking the controller's intentionally blocking shutdown path.
        adapter._closed = True
        adapter._thread.join(1)


class FailingController(FakeController):
    def __init__(self, exits=True):
        super().__init__()
        self.shutdown_called = Event()
        self.exits = exits

    def start_engine(self):
        raise RuntimeError("transport start failed")

    def shutdown(self):
        self.shutdown_called.set()

    def is_alive(self):
        return not self.exits


class FakeAudit:
    audit_failed = True

    def __init__(self):
        self._closed = False

    def confirm(self):
        return False

    def close(self):
        self._closed = True


class CommandFailingController(FakeController):
    def __init__(self, command):
        super().__init__()
        self.command = command
        self.shutdown_called = Event()

    def start(self, payload, run_id):
        if self.command == "START":
            raise RuntimeError("START command failed")
        return run_id

    def stop(self, run_id):
        if self.command == "STOP":
            raise RuntimeError("STOP command failed")

    def shutdown(self):
        self.shutdown_called.set()

    def is_alive(self):
        return False


def test_start_command_failure_escalates_to_verified_cleanup_without_run_success():
    controller = CommandFailingController("START")
    controller._audit = FakeAudit()
    adapter = MultiprocessGUIAdapter(controller, Queue(), lambda: {})
    adapter.start_engine()
    assert adapter.start()

    assert controller.shutdown_called.wait(1)
    adapter._thread.join(1)
    results = adapter.poll_results()

    assert any(name == "ERROR" for name, _, _ in results)
    assert any(name == "CLEANUP_COMPLETE" for name, _, _ in results)
    assert not any(name == "START_ACCEPTED" for name, _, _ in results)
    assert not adapter.is_active()
    assert not adapter.is_drained()
    assert adapter.cleanup_complete
    assert not adapter.shutdown_complete


def test_stop_command_failure_during_close_escalates_to_shutdown_cleanup():
    controller = CommandFailingController("STOP")
    controller._audit = FakeAudit()
    adapter = MultiprocessGUIAdapter(controller, Queue(), lambda: {})
    adapter.start_engine()
    adapter._run_id = "run-test"
    adapter._active = True
    adapter._drained = False
    adapter.shutdown_async()

    assert controller.shutdown_called.wait(1)
    adapter._thread.join(1)
    results = adapter.poll_results()

    assert any(name == "ERROR" for name, _, _ in results)
    assert any(name == "CLEANUP_COMPLETE" for name, _, _ in results)
    assert not any(name == "SHUTDOWN_COMPLETE" for name, _, _ in results)
    assert adapter.cleanup_complete
    assert not adapter.shutdown_complete
    assert not adapter.is_drained()


def test_rejected_start_return_escalates_instead_of_claiming_success():
    controller = CommandFailingController("NONE")
    controller.start = lambda payload, run_id: None
    controller._audit = FakeAudit()
    adapter = MultiprocessGUIAdapter(controller, Queue(), lambda: {})
    adapter.start_engine()
    assert adapter.start()

    assert controller.shutdown_called.wait(1)
    adapter._thread.join(1)
    results = adapter.poll_results()
    assert any(name == "ERROR" for name, _, _ in results)
    assert not any(name == "START_ACCEPTED" for name, _, _ in results)
    assert adapter.cleanup_complete
    assert not adapter.is_drained()


def test_transport_failure_attempts_cleanup_but_never_reports_drained_success():
    controller = FailingController()
    controller._audit = FakeAudit()
    adapter = MultiprocessGUIAdapter(controller, Queue(), lambda: {})
    adapter.start_engine()
    assert controller.shutdown_called.wait(1)
    adapter._thread.join(1)

    results = adapter.poll_results()
    assert any(name == "ERROR" for name, _, _ in results)
    assert any(name == "CLEANUP_COMPLETE" for name, _, _ in results)
    assert not any(name == "SHUTDOWN_COMPLETE" for name, _, _ in results)
    assert adapter.error is not None
    assert not adapter.is_drained()
    assert adapter.cleanup_complete
    assert not adapter.shutdown_complete


def test_transport_failure_does_not_confirm_cleanup_when_child_is_alive():
    controller = FailingController(exits=False)
    controller._audit = FakeAudit()
    adapter = MultiprocessGUIAdapter(controller, Queue(), lambda: {})
    adapter.start_engine()
    adapter._thread.join(1)

    assert adapter.error is not None
    assert not adapter.cleanup_complete
    assert not any(name == "CLEANUP_COMPLETE" for name, _, _ in adapter.poll_results())


def test_spawn_engine_gui_adapter_drains_and_audits_complete_run(tmp_path, monkeypatch):
    timeout = 15
    deadline = lambda: monotonic() + timeout
    payload = {
        "config": {
            "capacity": 1,
            "total_vehicles": 1,
            "min_arrival_time": 0,
            "max_arrival_time": 0,
            "min_parking_time": 0,
            "max_parking_time": 0,
        },
        "plate_sequence": ["GUI-001"],
        "authorization": {"vehicles": [
            {"plate": "GUI-001", "authorized": True, "space_id": 0},
        ]},
    }
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, queue_size=32, audit=audit)
    confirmed_runs = []
    confirm = audit.confirm

    def confirm_before_success(timeout=2.0):
        run_id = adapter._run_id
        if not confirmed_runs:
            assert run_id not in controller._finished
        result = confirm(timeout)
        confirmed_runs.append((run_id, result))
        return result

    monkeypatch.setattr(audit, "confirm", confirm_before_success)
    ui_events = Queue()
    adapter = MultiprocessGUIAdapter(controller, ui_events, lambda: payload)
    thread_started = False
    try:
        adapter.start_engine()
        thread_started = True
        assert adapter.start()
        run_id = adapter._run_id

        received = []
        end_by = deadline()
        while monotonic() < end_by:
            try:
                event = ui_events.get(timeout=min(0.1, max(0, end_by - monotonic())))
            except Empty:
                continue
            assert isinstance(event, ParkingEvent)
            received.append(event)
            if event.type == "SIMULATION_FINISHED":
                break
        else:
            raise AssertionError("timed out waiting for SIMULATION_FINISHED")

        assert [event.type for event in received].count("SIMULATION_STARTED") == 1
        assert [event.type for event in received].count("SIMULATION_FINISHED") == 1
        expected_event_keys = {
            (run_id, seq) for seq in range(controller._next_event_seq[run_id])
        }
        assert adapter._projected_events == expected_event_keys
        assert len(received) == len(expected_event_keys)
        assert all(event.vehicle_id is None or event.vehicle_id == 1 for event in received)
        assert adapter._run_id == run_id
        assert not adapter.is_active()
        assert adapter.is_drained()
        assert run_id in controller._finished
        assert confirmed_runs == [(run_id, True)]

        adapter.shutdown_async()
        adapter._thread.join(timeout)
        assert not adapter._thread.is_alive(), "adapter transport thread did not stop"
        assert not controller.is_alive()
        assert audit._closed
        assert audit.audit_complete
        log_contents = audit.path.read_text(encoding="utf-8")
        assert f"run_id={run_id}" in log_contents
        assert "event_type=SIMULATION_FINISHED" in log_contents
    finally:
        if thread_started and adapter._thread.is_alive():
            adapter.shutdown_async()
            adapter._thread.join(timeout)
        if controller.is_alive():
            controller.shutdown()
            controller.join(timeout)
        if not audit._closed:
            audit.close(timeout=timeout)
