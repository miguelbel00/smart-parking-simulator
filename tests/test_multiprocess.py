from simulation.ipc_protocol import parking_event_from_message, parking_event_to_message
from simulation.multiprocess import MultiprocessController
import time
import gc
import weakref
import pytest
from queue import Empty, Full, Queue
from simulation.multiprocess import _Publisher, _reap_finished
from simulation.audit_logging import AuditSession
import multiprocessing as mp


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


@pytest.fixture
def controlled_controller(monkeypatch):
    """Exercise real controller handlers with deterministic transport ordering."""
    from threading import Event

    class Process:
        exitcode = None
        alive = True
        joins = 0

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            self.joins += 1
            self.alive, self.exitcode = False, 0

    class Context:
        def Queue(self, maxsize):
            return Queue(maxsize=maxsize)

        def Event(self):
            return Event()

        def Process(self, **kwargs):
            return Process()

    monkeypatch.setattr(mp, "get_context", lambda context: Context())
    controller = MultiprocessController(capacity=1)
    monkeypatch.setattr(controller, "_timeout", .1)
    monkeypatch.setattr(controller, "_expected", {})
    return controller


def command_reply(command, run_id, request_id="req-1"):
    return {"v": 1, "kind": "reply", "run_id": run_id, "command": command,
            "request_id": request_id, "status": "accepted"}


def pre_reply_messages():
    from core.events import ParkingEvent

    return [
        parking_event_to_message(ParkingEvent("SIMULATION_STARTED", 1.0), "buffer-run", 0),
        {"v": 1, "kind": "audit", "run_id": "buffer-run", "seq": 0,
         "name": "REQUEST", "timestamp": 1.0, "payload": {"operation": "admission_attempt"}},
        parking_event_to_message(ParkingEvent("VEHICLE_CREATED", 2.0, vehicle_id=1,
                                 plate="ABC-1", authorized_space_id=0), "buffer-run", 1),
        {"v": 1, "kind": "audit", "run_id": "buffer-run", "seq": 1,
         "name": "REQUEST", "timestamp": 2.0, "payload": {"operation": "stop_requested"}},
    ]


@pytest.mark.parametrize("selection", [(0,), (1,), (0, 1, 2, 3)],
                         ids=["event", "audit", "mixed"])
def test_start_pre_reply_messages_have_one_public_delivery(controlled_controller, selection):
    controller = controlled_controller
    messages = pre_reply_messages()
    expected = [messages[index] for index in selection]
    for message in expected + [command_reply("START", "buffer-run")]:
        controller._output.put(message)

    assert controller.start(payload(), run_id="buffer-run") == "buffer-run"
    delivered = [controller.get(block=False) for _ in expected]
    assert delivered == expected
    # Event and audit sequence counters are independent channels.
    assert len({(m["kind"], m["run_id"], m["seq"]) for m in delivered}) == len(expected)
    with pytest.raises(Empty):
        controller.get(block=False)


@pytest.mark.parametrize("command,run_id", [
    ("START", "buffer-run"), ("STOP", "buffer-run"), ("SHUTDOWN", None),
])
def test_command_correlates_reply_without_rebuffering_messages(
        controlled_controller, command, run_id):
    controller = controlled_controller
    messages = pre_reply_messages()
    unrelated = command_reply("STOP", "other-run", "other-request")
    matched = command_reply(command, run_id)
    for message in messages + [unrelated, matched]:
        controller._output.put(message)

    assert controller._command(command, run_id, payload() if command == "START" else None) == matched
    sent = controller._commands.get_nowait()
    assert (sent["name"], sent["run_id"], sent["request_id"]) == (command, run_id, "req-1")
    # Preserve observed buffer order, not a new global cross-process order.
    expected = messages + [unrelated] + ([matched] if command == "SHUTDOWN" else [])
    assert [controller.get(block=False) for _ in expected] == expected
    with pytest.raises(Empty):
        controller.get(block=False)


@pytest.mark.parametrize("command,run_id,wrong_command,wrong_run", [
    ("START", "buffer-run", "STOP", "buffer-run"),
    ("START", "buffer-run", "START", "other-run"),
    ("STOP", "buffer-run", "START", "buffer-run"),
    ("STOP", "buffer-run", "STOP", "other-run"),
    ("SHUTDOWN", None, "STOP", "other-run"),
])
@pytest.mark.parametrize("source", ["output", "pending"])
def test_matching_request_id_does_not_accept_wrong_reply_scope(
        controlled_controller, command, run_id, wrong_command, wrong_run, source):
    controller = controlled_controller
    wrong = command_reply(wrong_command, wrong_run)
    if source == "output":
        controller._output.put(wrong)
    else:
        controller._pending.append(wrong)
    with pytest.raises(RuntimeError, match="reply correlation mismatch"):
        controller._command(command, run_id, payload() if command == "START" else None)


def test_stop_and_shutdown_preserve_pending_messages_and_join(controlled_controller):
    controller = controlled_controller
    expected = pre_reply_messages()
    for message in expected + [command_reply("START", "buffer-run")]:
        controller._output.put(message)
    controller.start(payload(), run_id="buffer-run")
    controller._output.put(command_reply("STOP", "buffer-run", "req-2"))
    controller.stop("buffer-run")
    shutdown_reply = command_reply("SHUTDOWN", None, "req-3")
    controller._output.put(shutdown_reply)
    controller.shutdown()

    assert not controller.is_alive() and controller._process.joins == 1
    assert [controller.get(block=False) for _ in range(len(expected) + 1)] == expected + [shutdown_reply]
    assert controller._pending == []
    assert [controller._commands.get_nowait()["name"] for _ in range(3)] == ["START", "STOP", "SHUTDOWN"]


def _raise_from_child_producer(output_queue, producer_entered, test_payload):
    from simulation import config
    from core.parking import ParkingLot
    from simulation.authorizations import Authorization, AuthorizationRegistry
    from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
    from simulation.multiprocess import _ChildAudit, _Publisher
    from simulation.simulator import Simulator

    record = test_payload["authorization"]["vehicles"][0]
    registry = AuthorizationRegistry({
        record["plate"]: Authorization(record["plate"], record["authorized"], record["space_id"])
    })
    config.MIN_ARRIVAL_TIME = 0
    config.MAX_ARRIVAL_TIME = 0
    publisher = _Publisher(output_queue, "exception-run")
    metrics = SimulationMetrics()

    def run_factory():
        forwarding = MetricsForwardingQueue(publisher, metrics)
        parking = ParkingLot(test_payload["config"]["capacity"], forwarding, registry)
        return parking, forwarding, metrics

    def fail_duration():
        producer_entered.set()
        raise ValueError("controlled producer failure")

    simulator = Simulator(run_factory, test_payload["plate_sequence"], duration_factory=fail_duration)
    simulator.set_audit(_ChildAudit(publisher))
    simulator.start(run_id="exception-run")
    producer_entered.wait(10)
    simulator.shutdown()


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
                event = parking_event_from_message(message)
                received.append(event.type)
                origin = message["origin"]
                assert set(origin) == {"process_id", "process_name", "thread_name"}
                assert type(origin["process_id"]) is int
                assert type(origin["process_name"]) is str
                assert type(origin["thread_name"]) is str
                assert origin["process_id"] == controller._process.pid
                expected_thread = {
                    "SIMULATION_STARTED": "simulation-producer",
                    "SIMULATION_FINISHED": "simulation-producer",
                    "VEHICLE_CREATED": "simulation-producer",
                    "VEHICLE_WAITING": "parking-admission",
                    "VEHICLE_ENTERED": "parking-admission",
                    "VEHICLE_EXITED": "parking-departures",
                    "VEHICLE_FINISHED": "parking-departures",
                }
                if event.type in expected_thread:
                    assert origin["thread_name"] == expected_thread[event.type]
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
        data = payload()
        data["plate_sequence"] += ["DENIED", "UNKNOWN"]
        data["authorization"]["vehicles"].append(
            {"plate": "DENIED", "authorized": False, "space_id": None})
        run_id = controller.start(data)
        received = {}
        while True:
            message = controller.get(timeout=10)
            if message.get("kind") == "event":
                # Buffered transport deliveries may repeat; auditing deduplicates
                # by the existing run/sequence key, not by caller get() count.
                received[message["seq"]] = parking_event_from_message(message)
            if message.get("kind") == "event" and message["name"] == "SIMULATION_FINISHED":
                break
        audit.close()
        contents = audit.path.read_text(encoding="utf-8")
        assert f"run_id={run_id}" in contents
        assert "admission_attempt" in contents
        assert "operation=admission_attempt" in contents
        admission = next(line for line in contents.splitlines()
                         if "operation=admission_attempt" in line)
        assert f"origin_process_id={controller._process.pid}" in admission
        assert f"origin_process_name=parking-engine" in admission
        assert "origin_thread_name=simulation-producer" in admission
        assert f"processName={__import__('multiprocessing').current_process().name}" in admission
        assert f"origin_process_id={controller._process.pid}" != f"origin_process_id={__import__('os').getpid()}"
        # Provenance is captured before the Core outbox can defer publication.
        event_line = next(line for line in contents.splitlines()
                          if "event_type=VEHICLE_ENTERED" in line)
        assert f"origin_process_id={controller._process.pid}" in event_line
        assert "origin_process_name=parking-engine" in event_line
        assert "origin_thread_name=parking-admission" in event_line
        assert f"processName={__import__('multiprocessing').current_process().name}" in event_line
        assert f"origin_process_id={controller._process.pid}" != f"origin_process_id={__import__('os').getpid()}"
        exit_line = next(line for line in contents.splitlines()
                         if "event_type=VEHICLE_EXITED" in line)
        assert f"origin_process_id={controller._process.pid}" in exit_line
        assert "origin_process_name=parking-engine" in exit_line
        assert "origin_thread_name=parking-departures" in exit_line
        assert "processName=MainProcess" in exit_line
        assert "origin_process_id=<Thread" not in exit_line
        assert "origin_thread_name=<Thread" not in exit_line
        finished_line = next(line for line in contents.splitlines()
                             if "event_type=VEHICLE_FINISHED" in line)
        assert "origin_thread_name=parking-departures" in finished_line
        started = next(line for line in contents.splitlines()
                       if "event_type=SIMULATION_STARTED" in line)
        assert f"origin_process_id={controller._process.pid}" in started
        assert "origin_thread_name=simulation-producer" in started
        records = [dict(field.split("=", 1) for field in line.split("\t"))
                   for line in contents.splitlines()]
        attempts = [record for record in records if record["operation"] == "admission_attempt"]
        decisions = [record for record in records
                     if record["event_type"] in ("VEHICLE_CREATED", "VEHICLE_REJECTED")]
        assert [(r["run_id"], r["vehicle_id"], r["plate"]) for r in attempts] == [
            (run_id, "1", "ABC-1"), (run_id, "2", "DENIED"), (run_id, "3", "UNKNOWN")]
        assert [(r["vehicle_id"], r["result"], r["reason"]) for r in decisions] == [
            ("1", "ACCEPTED", "-"), ("2", "REJECTED", "NOT_AUTHORIZED"),
            ("3", "REJECTED", "UNKNOWN_PLATE")]
        entered = next(event for event in received.values() if event.type == "VEHICLE_ENTERED")
        persisted = next(record for record in records if record["event_type"] == entered.type)
        assert float(persisted["waiting_time"]) == entered.waiting_time >= 0
        assert persisted["result"] == "PARKED"
        assert persisted["authorized_space_id"] == persisted["space_id"] == "0"
        assert len([r for r in records if r["record_kind"] == "event"]) == len(received)
    finally:
        if not audit.audit_complete:
            audit.close()
        controller.shutdown()
        controller.get(timeout=10)
        controller.join(10)


def test_spawn_child_producer_exception_preserves_origin_and_parent_writer(tmp_path):
    context = mp.get_context("spawn")
    output = context.Queue()
    producer_entered = context.Event()
    process = context.Process(target=_raise_from_child_producer,
                              args=(output, producer_entered, payload()), name="audit-test-child")
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, audit=audit)
    try:
        process.start()
        messages = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                message = output.get(timeout=.2)
            except Empty:
                if not process.is_alive():
                    break
                continue
            messages.append(message)
            if message.get("kind") == "audit" and message.get("name") == "ERROR":
                break
        if process.exitcode is None:
            process.join(max(0, deadline - time.monotonic()))
        process.join(10)
        assert not process.is_alive()
        assert process.exitcode == 0
        errors = [message for message in messages
                  if message.get("kind") == "audit" and message.get("name") == "ERROR"]
        assert errors, messages
        message = errors[0]
        assert message["kind"] == "audit"
        assert message["name"] == "ERROR"
        assert message["payload"]["record_kind"] == "exception"
        assert message["payload"]["operation"] == "producer_uncaught"
        assert message["payload"]["exception_type"] == "ValueError"
        assert message["payload"]["origin_process_id"] == process.pid
        assert message["payload"]["origin_process_name"] == process.name
        assert message["payload"]["origin_thread_name"] == "simulation-producer"
        assert type(message["payload"]["origin_process_id"]) is int
        assert all(type(message["payload"][key]) is str for key in
                   ("origin_process_name", "origin_thread_name"))
        for audit_message in messages:
            if audit_message.get("kind") == "audit":
                controller._handle_audit(audit_message)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        output.close()
        output.join_thread()
        audit.close()

    assert audit.audit_complete
    record = next(line for line in audit.path.read_text(encoding="utf-8").splitlines()
                  if "operation=producer_uncaught" in line)
    assert "level=ERROR" in record
    assert "operation=producer_uncaught" in record
    assert "exception_type=ValueError" in record
    assert f"origin_process_id={process.pid}" in record
    assert f"origin_process_name={process.name}" in record
    assert "origin_thread_name=simulation-producer" in record
    assert "processName=MainProcess" in record
    assert "threadName=MainThread" in record
    fields = dict(field.split("=", 1) for field in record.split("\t"))
    assert fields["error_summary"] == "ValueError: controlled producer failure\\n"
    assert fields["traceback"] == "-"


def test_child_error_summary_is_bounded_without_stack_details(tmp_path):
    from simulation.multiprocess import _ChildAudit

    output = Queue()
    child = _ChildAudit(_Publisher(output, "error-run"))
    child.exception("producer_uncaught", "error-run", ValueError("x" * 2000))
    message = output.get_nowait()
    assert message["v"] == 1 and message["name"] == "ERROR"
    assert len(message["payload"]["error"]) == 1000
    audit = AuditSession(tmp_path)
    try:
        audit.audit_record(message)
        assert audit.confirm()
    finally:
        audit.close()
    records = audit.path.read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    fields = dict(field.split("=", 1) for field in records[0].split("\t"))
    assert fields["error_summary"] == message["payload"]["error"]
    assert fields["traceback"] == "-" and fields["exception_type"] == "ValueError"


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
    parsed = [dict(field.split("=", 1) for field in line.split("\t")) for line in records]
    for current_run in run_ids:
        outcomes = [record["result"] for record in parsed
                    if record["run_id"] == current_run and record["vehicle_id"] == "1"
                    and record["record_kind"] == "event"]
        assert outcomes == ["ACCEPTED", "PARKED", "RELEASED", "FINISHED"]


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
    from simulation.ipc_protocol import validate_message

    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, audit=audit)
    event = ParkingEvent("SIMULATION_FINISHED", time.time())
    message = parking_event_to_message(event, "run-barrier", 0)
    assert validate_message(message) is message
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


def test_stop_active_run_drains_terminals_and_shutdown_joins_workers(tmp_path):
    data = payload()
    data["config"].update(total_vehicles=3, min_arrival_time=1, max_arrival_time=1,
                          min_parking_time=5, max_parking_time=5)
    data["plate_sequence"] = ["ABC-1", "DEF-2", "GHI-3"]
    data["authorization"]["vehicles"].extend((
        {"plate": "DEF-2", "authorized": True, "space_id": 0},
        {"plate": "GHI-3", "authorized": True, "space_id": 0},
    ))
    audit = AuditSession(tmp_path)
    controller = MultiprocessController(capacity=1, queue_size=32, audit=audit)
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
        audit.close()
    assert not controller.is_alive()
    assert audit.audit_complete
    records = [dict(field.split("=", 1) for field in line.split("\t"))
               for line in audit.path.read_text(encoding="utf-8").splitlines()]
    accepted = {record["vehicle_id"] for record in records
                if record["event_type"] == "VEHICLE_CREATED"}
    terminals = [record for record in records
                 if record["event_type"] in ("VEHICLE_FINISHED", "VEHICLE_CANCELLED")]
    assert {record["vehicle_id"] for record in terminals} == accepted
    assert len(terminals) == len(accepted)
    assert {record["run_id"] for record in terminals} == {run_id}
    cancelled = [record for record in terminals if record["result"] == "CANCELLED"]
    assert cancelled and all(record["reason"] == "STOP_REQUESTED" for record in cancelled)
    assert all(not any(r["event_type"] == "VEHICLE_ENTERED"
                       and r["vehicle_id"] == record["vehicle_id"] for r in records)
               for record in cancelled)


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
