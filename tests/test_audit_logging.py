import threading
import logging
from queue import Queue

import pytest

from core.events import ParkingEvent
from core.parking import ParkingLot
from simulation import config
from simulation.authorizations import Authorization, AuthorizationRegistry
from simulation.audit_logging import AuditSession
from simulation.metrics import MetricsForwardingQueue, SimulationMetrics
from simulation.simulator import Simulator


def rows(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_event_logged_once_with_original_time_context_and_unchanged_ui_queue(tmp_path):
    audit = AuditSession(tmp_path)
    run_id = audit.begin_run()
    ui = Queue()
    metrics = SimulationMetrics()
    forwarding = MetricsForwardingQueue(ui, metrics)
    forwarding.set_audit_context(audit, run_id)
    assert len(audit._logger.handlers) == 1
    event = ParkingEvent("VEHICLE_REJECTED", 1.0, 7, plate="Ñ-123", reason="NOT_AUTHORIZED")
    forwarding.put(event)
    assert ui.get_nowait() is event
    assert metrics.snapshot()["total_rejected"] == 1
    audit.close()
    log = rows(audit.path)
    assert len(log) == 1
    assert "event_type=VEHICLE_REJECTED" in log[0]
    assert "event_time=1970-01-01T00:00:01.000Z" in log[0]
    assert "plate=Ñ-123" in log[0]
    assert f"run_id={run_id}" in log[0]
    assert "threadName=MainThread" in log[0]
    expected_process_name = logging.LogRecord("test", logging.INFO, __file__, 1, "", (), None).processName
    assert f"processName={expected_process_name}" in log[0]
    assert "timestamp=" in log[0] and "level=INFO" in log[0]
    assert "reason=NOT_AUTHORIZED" in log[0]
    assert audit.audit_complete


def test_queue_listener_drains_records_and_runs_get_distinct_ids(tmp_path):
    audit = AuditSession(tmp_path)
    first = audit.begin_run()
    audit.operation("admission_attempt", first, vehicle_id=1, plate="ÁBC")
    audit.end_run(first)
    second = audit.begin_run()
    audit.operation("stop_requested", second)
    audit.close()
    text = "\n".join(rows(audit.path))
    assert first != second
    assert text.count("record_kind=operation") == 2
    assert first in text and second in text and "plate=ÁBC" in text
    assert text.count("operation=stop_requested") == 1


def test_exception_hook_captures_real_parking_worker_failure_and_delegates(tmp_path, monkeypatch):
    from core.parking import ParkingLot

    delegated = threading.Event()
    prior = lambda args: delegated.set()
    monkeypatch.setattr(threading, "excepthook", prior)
    monkeypatch.setattr(ParkingLot, "_admission_worker",
                        lambda self: (_ for _ in ()).throw(ValueError("worker diagnostic")))
    audit = AuditSession(tmp_path)
    run_id = audit.begin_run()
    lot = ParkingLot(1, MetricsForwardingQueue(Queue(), SimulationMetrics()),
                     AuthorizationRegistry({}))
    lot.start()
    lot.close(wait=True)
    assert delegated.wait(1)
    audit.end_run(run_id)
    audit.close()
    text = "\n".join(rows(audit.path))
    assert "exception_type=ValueError" in text
    assert "worker diagnostic" in text
    assert f"run_id={run_id}" in text
    assert "threadName=parking-admission" in text
    expected_process_name = logging.LogRecord("test", logging.INFO, __file__, 1, "", (), None).processName
    assert f"processName={expected_process_name}" in text
    assert threading.excepthook is prior


def test_file_initialization_failure_is_visible(tmp_path, monkeypatch):
    from simulation import audit_logging

    def fail(*args, **kwargs):
        raise OSError("cannot open audit file")

    monkeypatch.setattr(audit_logging.logging.FileHandler, "__init__", fail)
    with pytest.raises(OSError, match="cannot open audit file"):
        AuditSession(tmp_path)


def test_handler_failure_marks_audit_incomplete_without_propagating(tmp_path, capsys, monkeypatch):
    audit = AuditSession(tmp_path)
    run_id = audit.begin_run()

    class BrokenStream:
        def write(self, value):
            raise OSError("disk full")

        def flush(self):
            pass

    monkeypatch.setattr(audit._file_handler, "stream", BrokenStream())
    audit.operation("admission_attempt", run_id, vehicle_id=3, plate="X")
    audit.close()
    assert audit.audit_failed
    assert not audit.audit_complete
    assert "Parking audit incomplete (file handler): OSError: disk full" in capsys.readouterr().err


def test_audit_queue_failure_is_non_propagating_and_marks_incomplete(tmp_path, capsys, monkeypatch):
    audit = AuditSession(tmp_path)

    def fail(record):
        raise OSError("audit queue unavailable")

    monkeypatch.setattr(audit._records, "put_nowait", fail)
    audit.operation("admission_attempt", audit.begin_run(), vehicle_id=1, plate="A")
    monkeypatch.undo()
    audit.close()
    assert audit.audit_failed
    assert "Parking audit incomplete (audit queue): OSError: audit queue unavailable" in capsys.readouterr().err


def test_concurrent_event_order_matches_ui_publication_order(tmp_path):
    from threading import Barrier, Thread

    class OrderedQueue(Queue):
        def __init__(self):
            super().__init__()
            self.published = []

        def put(self, item, block=True, timeout=None):
            self.published.append(item.vehicle_id)
            super().put(item, block=block, timeout=timeout)

    audit = AuditSession(tmp_path)
    run_id = audit.begin_run()
    destination = OrderedQueue()
    forwarding = MetricsForwardingQueue(destination, SimulationMetrics())
    forwarding.set_audit_context(audit, run_id)
    barrier = Barrier(5)

    def publish(vehicle_id):
        barrier.wait()
        forwarding.put(ParkingEvent("VEHICLE_CREATED", float(vehicle_id), vehicle_id=vehicle_id))

    workers = [Thread(target=publish, args=(vehicle_id,)) for vehicle_id in range(1, 5)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()
    audit.close()
    logged = [int(line.split("vehicle_id=", 1)[1].split("\t", 1)[0])
              for line in rows(audit.path) if "record_kind=event" in line]
    assert logged == destination.published


def test_simulator_logs_each_admission_attempt_and_event_for_two_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    ui = Queue()
    registry = AuthorizationRegistry({
        "OK": Authorization("OK", True, 0),
        "NO": Authorization("NO", False, None),
    })
    executions = []
    admissions = 0
    admissions_changed = threading.Condition()
    original_admit = ParkingLot.admit

    def synchronized_admit(lot, vehicle):
        nonlocal admissions
        result = original_admit(lot, vehicle)
        with admissions_changed:
            admissions += 1
            admissions_changed.notify_all()
        return result

    monkeypatch.setattr(ParkingLot, "admit", synchronized_admit)

    def factory():
        metrics = SimulationMetrics()
        forwarding = MetricsForwardingQueue(ui, metrics)
        lot = ParkingLot(1, forwarding, registry)
        executions.append((lot, metrics))
        return lot, forwarding, metrics

    audit = AuditSession(tmp_path)
    simulator = Simulator(factory, ["OK", "NO"], duration_factory=lambda: 0)
    simulator.set_audit(audit)
    for _ in range(2):
        with admissions_changed:
            expected_admissions = admissions + 2
        assert simulator.start()
        with admissions_changed:
            assert admissions_changed.wait_for(lambda: admissions >= expected_admissions, timeout=2)
        simulator.shutdown()
    audit.close()
    log = "\n".join(rows(audit.path))
    run_ids = {line.split("run_id=", 1)[1].split("\t", 1)[0]
               for line in rows(audit.path) if "record_kind=event" in line}
    assert len(run_ids) == 2
    assert log.count("operation=admission_attempt") == 4
    assert log.count("event_type=VEHICLE_REJECTED") == 2
    assert log.count("event_type=VEHICLE_CREATED") == 2
    assert all(isinstance(event, ParkingEvent) for event in list(ui.queue))
    assert all(metrics.snapshot()["total_rejected"] == 1 for _, metrics in executions)


def test_producer_exception_is_logged_with_run_id_and_worker_drain(tmp_path, monkeypatch):
    monkeypatch.setattr(threading, "excepthook", lambda args: None)
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    monkeypatch.setattr(ParkingLot, "admit", lambda *_: (_ for _ in ()).throw(RuntimeError("producer fault")))
    registry = AuthorizationRegistry({"OK": Authorization("OK", True, 0)})
    metrics = SimulationMetrics()
    ui = Queue()

    def factory():
        forwarding = MetricsForwardingQueue(ui, metrics)
        return ParkingLot(1, forwarding, registry), forwarding, metrics

    audit = AuditSession(tmp_path)
    simulator = Simulator(factory, ["OK"], duration_factory=lambda: 0)
    simulator.set_audit(audit)
    simulator.start()
    simulator.shutdown()
    audit.close()
    text = "\n".join(rows(audit.path))
    assert "operation=producer_uncaught" in text
    assert "exception_type=RuntimeError" in text and "producer fault" in text
    assert text.count("operation=admission_attempt") == 1
    assert f"run_id={simulator._run_id}" in text


def test_repeated_stop_intent_is_logged_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 1)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 1)
    registry = AuthorizationRegistry({"OK": Authorization("OK", True, 0)})
    ui = Queue()

    def factory():
        metrics = SimulationMetrics()
        forwarding = MetricsForwardingQueue(ui, metrics)
        return ParkingLot(1, forwarding, registry), forwarding, metrics

    audit = AuditSession(tmp_path)
    simulator = Simulator(factory, ["OK"])
    simulator.set_audit(audit)
    simulator.start()
    simulator.stop()
    simulator.stop()
    simulator.shutdown()
    audit.close()
    assert "operation=stop_requested" in "\n".join(rows(audit.path))
    assert "\n".join(rows(audit.path)).count("operation=stop_requested") == 1


def test_run_factory_failure_is_audited_without_a_run_id(tmp_path):
    audit = AuditSession(tmp_path)

    def fail_factory():
        raise ValueError("run factory failed")

    simulator = Simulator(fail_factory, [])
    simulator.set_audit(audit)
    with pytest.raises(ValueError, match="run factory failed"):
        simulator.start()
    audit.close()
    text = "\n".join(rows(audit.path))
    assert "operation=run_setup" in text
    assert "run_id=-" in text
    assert "exception_type=ValueError" in text and "run factory failed" in text


def test_publication_failure_is_logged_once_not_as_cleanup_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(threading, "excepthook", lambda args: None)
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 0)
    registry = AuthorizationRegistry({"OK": Authorization("OK", True, 0)})
    ui = Queue()

    class FailingPublicationQueue:
        def __init__(self, destination):
            self.destination = destination

        def set_audit_context(self, audit, run_id):
            self.destination.set_audit_context(audit, run_id)

        def put(self, item, block=True, timeout=None):
            if item.type == "VEHICLE_CREATED":
                raise OSError("publication failed")
            self.destination.put(item, block=block, timeout=timeout)

    def factory():
        metrics = SimulationMetrics()
        forwarder = MetricsForwardingQueue(ui, metrics)
        event_queue = FailingPublicationQueue(forwarder)
        return ParkingLot(1, event_queue, registry), event_queue, metrics

    audit = AuditSession(tmp_path)
    simulator = Simulator(factory, ["OK"], duration_factory=lambda: 0)
    simulator.set_audit(audit)
    simulator.start()
    simulator.shutdown()
    audit.close()
    text = "\n".join(rows(audit.path))
    assert "publication failed" in text
    assert text.count("record_kind=exception") == 1
    assert "operation=producer_uncaught" in text
    assert "operation=producer_cleanup" not in text


def test_shutdown_joins_producer_even_when_stop_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MIN_ARRIVAL_TIME", 30)
    monkeypatch.setattr(config, "MAX_ARRIVAL_TIME", 30)
    registry = AuthorizationRegistry({"OK": Authorization("OK", True, 0)})
    ui = Queue()
    lots = []

    def factory():
        metrics = SimulationMetrics()
        forwarder = MetricsForwardingQueue(ui, metrics)
        lot = ParkingLot(1, forwarder, registry)
        lots.append(lot)
        original_close = lot.close

        def close(wait=True, cancel_pending=True):
            original_close(wait=wait, cancel_pending=cancel_pending)
            if not wait:
                raise OSError("stop close reported failure")

        lot.close = close
        return lot, forwarder, metrics

    audit = AuditSession(tmp_path)
    simulator = Simulator(factory, ["OK"])
    simulator.set_audit(audit)
    simulator.start()
    with pytest.raises(OSError, match="stop close reported failure"):
        simulator.shutdown()
    assert not simulator.is_active()
    assert simulator.is_drained()
    assert all(not lot._admission_thread.is_alive() and not lot._departure_thread.is_alive()
               for lot in lots)
    audit.close()
def test_confirm_barrier_waits_for_file_handler_and_flushes(tmp_path):
    audit = AuditSession(tmp_path)
    audit.operation("before_barrier", "run-1")
    assert audit.confirm(timeout=1)
    assert "operation=before_barrier" in audit.path.read_text(encoding="utf-8")
    audit.close(timeout=1)
    assert audit.audit_complete


def test_confirm_detects_writer_failure_before_barrier_completes(tmp_path, monkeypatch):
    audit = AuditSession(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    original = audit._file_handler.emit

    def failing_emit(record):
        if getattr(record, "operation", None) == "slow":
            entered.set()
            release.wait(1)
            audit._mark_failed("test writer", OSError("injected failure"))
            return
        original(record)

    monkeypatch.setattr(audit._file_handler, "emit", failing_emit)
    audit.operation("slow", "run-1")
    assert entered.wait(1)
    result = []
    waiter = threading.Thread(target=lambda: result.append(audit.confirm(timeout=1)))
    waiter.start()
    release.set()
    waiter.join(2)
    assert not waiter.is_alive()
    assert result == [False]
    assert audit.audit_failed
    audit.close(timeout=1)


def test_close_timeout_marks_audit_incomplete_without_unbounded_join(tmp_path, monkeypatch):
    audit = AuditSession(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    original = audit._file_handler.emit
    file_stream = audit._file_handler.stream

    def blocked(record):
        entered.set()
        release.wait(1)
        original(record)

    monkeypatch.setattr(audit._file_handler, "emit", blocked)
    audit.operation("blocked", "run-1")
    assert entered.wait(1)
    with pytest.raises(TimeoutError, match="listener did not stop"):
        audit.close(timeout=.01)
    assert audit.audit_failed
    assert not audit.audit_complete
    release.set()
    audit.close(timeout=1)
    assert not audit._listener_thread.is_alive()
    assert file_stream.closed
    assert audit._file_handler.stream is None
    assert not audit.audit_complete
