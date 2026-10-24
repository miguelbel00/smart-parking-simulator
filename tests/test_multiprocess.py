from simulation.ipc_protocol import parking_event_from_message, parking_event_to_message
from simulation.multiprocess import MultiprocessController
import time
import gc
import weakref
import pytest
from queue import Empty, Full, Queue
from simulation.multiprocess import _Publisher, _reap_finished
from simulation.audit_logging import AuditSession


def payload():
    return {
        "config": {
            "capacity": 1,
            "total_vehicles": 1,
            "min_arrival_time": 0,
            "max_arrival_time": 0,
            "min_parking_time": 0,
            "max_parking_time": 0,
        },
        "plate_sequence": ["ABC-1"],
        "authorization": {"vehicles": [
            {"plate": "ABC-1", "authorized": True, "space_id": 0},
        ]},
    }


def test_reaper_removes_only_drained_inactive_simulators():
    class Stub:
        def __init__(self, drained, active):
            self.drained = drained
            self.active = active

        def is_drained(self):
            return self.drained

        def is_active(self):
            return self.active

    safe = Stub(True, False)
    active = Stub(True, True)
    not_drained = Stub(False, False)
    simulators = {"safe": safe, "active": active, "not-drained": not_drained}
    safe_ref = weakref.ref(safe)
    _reap_finished(simulators)
    assert simulators == {"active": active, "not-drained": not_drained}
    del safe
    gc.collect()
    assert safe_ref() is None


def test_spawn_engine_runs_simulation_and_publishes_ordered_terminal_events():
    controller = MultiprocessController(capacity=1, queue_size=32)
    controller.start_engine()
    try:
        run_id = controller.start(payload())
        received = []
        while True:
            message = controller.get(timeout=10)
            if message.get("kind") == "event":
                assert message["run_id"] == run_id
                received.append(parking_event_from_message(message).type)
                if message["name"] == "SIMULATION_FINISHED":
                    break
        assert received[0] == "SIMULATION_STARTED"
        assert received[-1] == "SIMULATION_FINISHED"
        assert received.index("VEHICLE_FINISHED") < received.index("SIMULATION_FINISHED")
    finally:
        controller.shutdown()
        controller.get(timeout=10)
        controller.join(timeout=10)
    assert not controller.is_alive()


def test_spawn_engine_has_distinct_pid_and_successive_runs_are_isolated():
    controller = MultiprocessController(capacity=1, queue_size=32)
    controller.start_engine()
    try:
        assert controller._process.pid != __import__("os").getpid()
        first = controller.start(payload())
        with pytest.raises(RuntimeError, match="already active"):
            controller.start(payload())
        while True:
            message = controller.get(timeout=10)
            if message.get("kind") == "event" and message["name"] == "SIMULATION_FINISHED":
                break
        second = controller.start(payload())
        assert first != second
        finished = {first}
        deadline = time.monotonic() + 10
        while len(finished) != 2 and time.monotonic() < deadline:
            event = controller.get(timeout=max(.01, deadline-time.monotonic()))
            if event.get("kind") == "event" and event["name"] == "SIMULATION_FINISHED":
                finished.add(event["run_id"])
        assert finished == {first, second}
    finally:
        controller.shutdown()
        controller.join(10)
    assert not controller.is_alive()


def test_child_audit_records_are_forwarded_to_parent_session(tmp_path):
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, queue_size=32, audit=audit)
    controller.start_engine()
    try:
        run_id = controller.start(payload())
        while True:
            message = controller.get(timeout=10)
            if message.get("kind") == "event" and message["name"] == "SIMULATION_FINISHED":
                break
        audit.close()
        contents = audit.path.read_text(encoding="utf-8")
        assert f"run_id={run_id}" in contents
        assert "admission_attempt" in contents
        assert "operation=admission_attempt" in contents
    finally:
        if not audit.audit_complete:
            audit.close()
        controller.shutdown()
        controller.get(timeout=10)
        controller.join(10)


def test_sequential_spawn_runs_share_audited_parent_session(tmp_path, monkeypatch):
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, queue_size=32, audit=audit)
    confirms = []
    original_confirm = audit.confirm

    def confirm_after_audit(timeout):
        # The finish handler must not publish success before the parent audit
        # listener has flushed every record received ahead of this barrier.
        assert run_id not in controller._finished
        result = original_confirm(timeout)
        confirms.append((run_id, result))
        return result

    monkeypatch.setattr(audit, "confirm", confirm_after_audit)
    run_ids = []
    controller.start_engine()
    try:
        first = controller.start(payload(), run_id="run-1")
        run_id = first
        run_ids.append(first)
        deadline = time.monotonic() + 10
        while True:
            message = controller.get(timeout=max(.01, deadline - time.monotonic()))
            if (message.get("kind") == "event" and message["run_id"] == first
                    and message["name"] == "SIMULATION_FINISHED"):
                break
            assert time.monotonic() < deadline, "timed out waiting for simulation finish"
        assert controller._finished >= {first}
        assert confirms[-1] == (first, True)

        # Previously supplied IDs are permanently reserved; rejected reuse
        # must not start another audit run or send a child command.
        audit_begins = sum("operation=run_requested" in line for line in audit.path.read_text(encoding="utf-8").splitlines())
        request_before = controller._request
        with pytest.raises(RuntimeError, match="already been used"):
            controller.start(payload(), run_id=first)
        assert controller._request == request_before
        assert sum("operation=run_requested" in line for line in audit.path.read_text(encoding="utf-8").splitlines()) == audit_begins

        # The auto-generated sequence skips run-1 because it was supplied.
        for _ in range(2):
            run_id = controller.start(payload())
            run_ids.append(run_id)
            deadline = time.monotonic() + 10
            while True:
                message = controller.get(timeout=max(.01, deadline - time.monotonic()))
                if (message.get("kind") == "event"
                        and message["run_id"] == run_id
                        and message["name"] == "SIMULATION_FINISHED"):
                    break
                assert time.monotonic() < deadline, "timed out waiting for simulation finish"
            assert controller._finished >= {run_id}
            assert confirms[-1] == (run_id, True)

        assert len(confirms) == 3
        assert len(set(run_ids)) == 3
        assert controller._finished >= set(run_ids)
    finally:
        controller.shutdown()
        controller.join(10)
        assert not controller.is_alive()
        audit.close()

    assert audit.audit_complete
    records = audit.path.read_text(encoding="utf-8").splitlines()
    finish_records = [line for line in records
                      if "record_kind=event" in line
                      and "event_type=SIMULATION_FINISHED" in line]
    assert len(finish_records) == 3
    assert {line.split("run_id=", 1)[1].split("\t", 1)[0]
            for line in finish_records} == set(run_ids)


def test_multiple_spawn_runs_stop_waiter_and_audit_all_terminals(tmp_path):
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, queue_size=32, audit=audit)
    controller.start_engine()
    run_ids = []

    def receive_until(predicate, timeout=20):
        deadline = time.monotonic() + timeout
        received = []
        while time.monotonic() < deadline:
            try:
                message = controller.get(timeout=max(.01, deadline - time.monotonic()))
            except Empty:
                break
            received.append(message)
            if predicate(message):
                return received
        pytest.fail(f"timed out waiting for expected child message; received={received!r}")

    try:
        for run_id in ("multi-1", "multi-2"):
            actual_id = controller.start(payload(), run_id=run_id)
            run_ids.append(actual_id)
            receive_until(lambda message: message.get("kind") == "event"
                          and message["run_id"] == actual_id
                          and message["name"] == "SIMULATION_FINISHED")
            assert actual_id in controller._finished

        data = payload()
        data["config"].update(total_vehicles=1, min_arrival_time=10,
                              max_arrival_time=10)
        stopped_run = controller.start(data, run_id="multi-3")
        run_ids.append(stopped_run)
        controller.stop(stopped_run)
        terminals = receive_until(
            lambda message: message.get("kind") == "event"
            and message["run_id"] == stopped_run
            and message["name"] == "SIMULATION_FINISHED"
        )
        run_events = {
            message["seq"]: message["name"]
            for message in terminals
            if message.get("kind") == "event"
            and message["run_id"] == stopped_run
        }
        assert list(run_events.values()) == ["SIMULATION_STARTED", "SIMULATION_FINISHED"]
        assert stopped_run in controller._finished
    finally:
        if controller.is_alive():
            controller.shutdown()
            controller.join(10)
        audit.close()

    assert not controller.is_alive()
    assert audit.audit_complete
    records = audit.path.read_text(encoding="utf-8").splitlines()
    finish_records = [line for line in records
                      if "record_kind=event" in line
                      and "event_type=SIMULATION_FINISHED" in line]
    assert len(finish_records) == 3
    assert {line.split("run_id=", 1)[1].split("\t", 1)[0]
            for line in finish_records} == set(run_ids)


def test_simulation_finish_requires_audit_barrier_and_preserves_finished_compatibility(tmp_path):
    from core.events import ParkingEvent

    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, audit=audit)
    event = ParkingEvent("SIMULATION_FINISHED", time.time())
    message = parking_event_to_message(event, "run-barrier", 0)
    controller._handle_event(message)
    assert controller._terminal_received == {"run-barrier"}
    assert controller._finished == {"run-barrier"}
    audit.close()


def test_simulation_finish_preexisting_audit_failure_does_not_succeed(tmp_path):
    from core.events import ParkingEvent

    audit = AuditSession(tmp_path)
    audit._mark_failed("test", OSError("known failure"))
    controller = MultiprocessController(capacity=1, audit=audit)
    message = parking_event_to_message(ParkingEvent("SIMULATION_FINISHED", time.time()), "failed", 0)
    with pytest.raises(RuntimeError, match="audit incomplete"):
        controller._handle_event(message)
    assert "failed" in controller._terminal_received
    assert "failed" not in controller._finished
    audit.close()


def test_failure_arriving_during_finish_barrier_prevents_success(tmp_path, monkeypatch):
    from core.events import ParkingEvent

    audit = AuditSession(tmp_path)
    reached = __import__("threading").Event()
    release = __import__("threading").Event()

    def confirm(timeout):
        reached.set()
        release.wait(timeout)
        return not audit.audit_failed

    monkeypatch.setattr(audit, "confirm", confirm)
    controller = MultiprocessController(capacity=1, audit=audit)
    message = parking_event_to_message(ParkingEvent("SIMULATION_FINISHED", time.time()), "late", 0)
    errors = []
    worker = __import__("threading").Thread(
        target=lambda: _capture_error(errors, lambda: controller._handle_event(message))
    )
    worker.start()
    assert reached.wait(1)
    audit._mark_failed("late writer", OSError("disk failure"))
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert errors and "audit incomplete" in str(errors[0])
    assert "late" not in controller._finished
    audit.close()


def _capture_error(errors, action):
    try:
        action()
    except BaseException as error:
        errors.append(error)


def test_publisher_fails_closed_on_bounded_queue_full():
    destination = Queue(maxsize=1)
    destination.put(object())
    publisher = _Publisher(destination, "run-full", timeout=0.01)
    from core.events import ParkingEvent
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="queue remained full"):
        publisher.put(ParkingEvent("SIMULATION_STARTED", time.time()))
    assert time.monotonic() - started < 0.5
    assert publisher.dropped == 1
    assert publisher.failed


def test_stop_active_run_drains_terminals_and_shutdown_joins_workers():
    data = payload()
    data["config"].update(total_vehicles=3, min_arrival_time=1, max_arrival_time=1,
                          min_parking_time=5, max_parking_time=5)
    data["plate_sequence"] = ["ABC-1", "DEF-2", "GHI-3"]
    data["authorization"]["vehicles"].extend((
        {"plate": "DEF-2", "authorized": True, "space_id": 0},
        {"plate": "GHI-3", "authorized": True, "space_id": 0},
    ))
    controller = MultiprocessController(capacity=1, queue_size=32)
    controller.start_engine()
    try:
        run_id = controller.start(data)
        initial = []
        while True:
            message = controller.get(timeout=10)
            if message.get("kind") == "event" and message["run_id"] == run_id:
                initial.append(message["name"])
                if (message["name"] == "VEHICLE_CREATED"
                        and message["payload"]["vehicle_id"] == 2):
                    break
        controller.stop(run_id)
        terminal_events = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            message = controller.get(timeout=max(.01, deadline - time.monotonic()))
            if message.get("kind") == "event" and message["run_id"] == run_id:
                terminal_events.append(message["name"])
                if message["name"] == "SIMULATION_FINISHED":
                    break
        assert terminal_events[-1] == "SIMULATION_FINISHED"
        finished_index = terminal_events.index("SIMULATION_FINISHED")
        assert "VEHICLE_CANCELLED" in terminal_events[:finished_index]
        assert "VEHICLE_FINISHED" in terminal_events[:finished_index]
        assert controller._finished == {run_id}
        assert controller._process.is_alive()
    finally:
        controller.shutdown()
        controller.join(10)
    assert not controller.is_alive()


def test_audit_sequence_gap_marks_audit_incomplete(tmp_path):
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, audit=audit)
    try:
        with pytest.raises(RuntimeError, match="audit sequence"):
            controller._handle_audit({"v": 1, "kind": "audit", "run_id": "gap", "seq": 1,
                                      "name": "REQUEST", "timestamp": time.time(),
                                      "payload": {"operation": "x"}})
        assert audit.audit_failed
    finally:
        audit.close()


def test_lost_middle_event_then_later_event_marks_run_and_audit_incomplete(tmp_path):
    from core.events import ParkingEvent

    class DropMiddleEventQueue:
        def __init__(self):
            self.messages = []
            self.calls = 0

        def put(self, message, timeout=None):
            self.calls += 1
            if self.calls == 2:
                raise Full
            self.messages.append(message)

    destination = DropMiddleEventQueue()
    failed = __import__("threading").Event()
    publisher = _Publisher(destination, "gap", timeout=0.01, failure_signal=failed)
    events = [ParkingEvent("SIMULATION_STARTED", 0.0),
              ParkingEvent("VEHICLE_CREATED", 1.0, vehicle_id=1, plate="ABC-1",
                           authorized_space_id=0),
              ParkingEvent("SIMULATION_FINISHED", 2.0)]
    publisher.put(events[0])
    with pytest.raises(RuntimeError, match="queue remained full"):
        publisher.put(events[1])
    # Model a faulty/late source bypassing the failed publisher after seq=1
    # was lost. The controller must detect this gap; the publisher must not
    # produce the later event itself.
    with pytest.raises(RuntimeError, match="publisher failed"):
        publisher.put(events[2])
    assert destination.calls == 2
    destination.messages.append(parking_event_to_message(events[2], "gap", 2))
    assert failed.is_set()

    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, audit=audit)
    try:
        controller._handle_event(destination.messages[0])
        with pytest.raises(RuntimeError, match="non-contiguous event sequence"):
            controller._handle_event(destination.messages[1])
        assert audit.audit_failed
    finally:
        audit.close()


def test_observed_transport_failure_marks_attached_audit_incomplete(tmp_path):
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, audit=audit)
    try:
        controller._transport_failed.set()
        with pytest.raises(RuntimeError, match="transport failed"):
            controller.get(block=False)
        assert audit.audit_failed
    finally:
        audit.close()


def test_shutdown_raises_if_engine_remains_alive(monkeypatch):
    class StuckProcess:
        def join(self, timeout):
            self.timeout = timeout

        def is_alive(self):
            return True

    controller = MultiprocessController(capacity=1)
    process = StuckProcess()
    controller._process = process
    controller._timeout = 0.01
    monkeypatch.setattr(controller, "_command", lambda *args, **kwargs: None)
    with pytest.raises(TimeoutError, match="did not stop"):
        controller.shutdown()
    assert process.timeout == controller._timeout


def test_spawn_output_saturation_is_incomplete_but_shutdown_drains_and_joins(tmp_path):
    data = payload()
    plates = [f"CAR-{index}" for index in range(40)]
    data["config"].update(total_vehicles=len(plates), min_arrival_time=0,
                          max_arrival_time=0, min_parking_time=0,
                          max_parking_time=0)
    data["plate_sequence"] = plates
    data["authorization"]["vehicles"] = [
        {"plate": plate, "authorized": True, "space_id": 0} for plate in plates
    ]
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, queue_size=1, audit=audit)
    controller._timeout = 5
    controller.start_engine()
    try:
        run_id = controller.start(data)
        # Leave the bounded output queue undrained so saturation is deterministic.
        assert controller._transport_failed.wait(10)
        with pytest.raises(RuntimeError) as failure:
            controller.get(timeout=0)
        assert "transport failed" in str(failure.value) or "engine failed" in str(failure.value)
        assert run_id not in controller._finished
        assert audit.audit_failed

        started = time.monotonic()
        controller.shutdown()
        assert time.monotonic() - started < 6
        assert not controller.is_alive()
    finally:
        if controller.is_alive():
            controller.shutdown()
        audit.close()


def test_get_detects_abrupt_engine_death_with_bounded_wait():
    controller = MultiprocessController(capacity=1)
    controller.start_engine()
    controller._timeout = 1
    try:
        controller._process.terminate()  # deliberate fault injection for death detection
        controller.join(5)
        with pytest.raises(RuntimeError, match="unexpectedly"):
            controller._ensure_engine()
    finally:
        controller.join(5)
