"""Composition test without constructing a Tk root."""

from queue import Empty
from time import monotonic, sleep

from simulation.authorizations import Authorization, AuthorizationRegistry

import main as entry


def test_main_composes_fresh_runs_and_reports_only_latest(monkeypatch, capsys, tmp_path):
    from simulation.audit_logging import AuditSession
    monkeypatch.setattr(entry, "AuditSession", lambda: AuditSession(tmp_path / "logs"))
    monkeypatch.setattr(entry.config, "PARKING_CAPACITY", 2)
    monkeypatch.setattr(entry.config, "TOTAL_VEHICLES", 1)
    monkeypatch.setattr(entry.config, "MIN_ARRIVAL_TIME", 0)
    monkeypatch.setattr(entry.config, "MAX_ARRIVAL_TIME", 0)
    monkeypatch.setattr(entry.config, "MIN_PARKING_TIME", 0)
    monkeypatch.setattr(entry.config, "MAX_PARKING_TIME", 0)
    observed = []
    lots = []
    real_lot = entry.ParkingLot

    def capture_lot(capacity, event_queue, authorization_registry):
        lot = real_lot(capacity=capacity, event_queue=event_queue,
                       authorization_registry=authorization_registry)
        lots.append(lot)
        return lot

    monkeypatch.setattr(entry, "ParkingLot", capture_lot)

    class FakeApp:
        def __init__(self, event_queue, simulator, capacity):
            assert capacity == 2
            self.event_queue = event_queue
            self.simulator = simulator

        def run(self):
            for _ in range(2):
                assert self.simulator.start() is True
                deadline = monotonic() + 3
                while self.simulator.is_active() and monotonic() < deadline:
                    sleep(0.001)
                assert not self.simulator.is_active()
                assert self.simulator.is_drained()
                observed.append(self.simulator.metrics)
            events = []
            while True:
                try:
                    events.append(self.event_queue.get_nowait())
                except Empty:
                    break
            assert [e.type for e in events].count("SIMULATION_STARTED") == 2
            assert [e.type for e in events].count("SIMULATION_FINISHED") == 2

    monkeypatch.setattr(entry, "ParkingApp", FakeApp)
    monkeypatch.setattr(entry.config, "PLATE_SEQUENCE", ("EDU-001",))
    monkeypatch.setattr(entry, "load_authorizations", lambda *_: AuthorizationRegistry({
        "EDU-001": Authorization("EDU-001", True, 0),
    }))
    entry.main()
    assert len(lots) == 2 and lots[0] is not lots[1]
    assert all(lot.capacity == 2 for lot in lots)
    assert observed[0] is not observed[1]
    assert observed[0].snapshot()["total_generated"] == 1
    assert observed[1].snapshot()["total_generated"] == 1
    assert capsys.readouterr().out == observed[1].report() + "\n"


def test_main_without_run_does_not_print_statistics(monkeypatch, capsys, tmp_path):
    from simulation.audit_logging import AuditSession
    monkeypatch.setattr(entry, "AuditSession", lambda: AuditSession(tmp_path / "logs"))
    class FakeApp:
        def __init__(self, event_queue, simulator, capacity):
            pass

        def run(self):
            pass

    monkeypatch.setattr(entry, "ParkingApp", FakeApp)
    entry.main()
    assert capsys.readouterr().out == ""


def test_invalid_authorization_file_prevents_run_start(monkeypatch, tmp_path):
    from simulation.audit_logging import AuditSession
    monkeypatch.setattr(entry, "AuditSession", lambda: AuditSession(tmp_path / "logs"))
    bad_file = tmp_path / "invalid.json"
    bad_file.write_text('{"vehicles": [}', encoding="utf-8")
    monkeypatch.setattr(entry.config, "AUTHORIZATION_FILE", bad_file)
    monkeypatch.setattr(entry.config, "PLATE_SEQUENCE", ("A",))

    class FakeApp:
        def __init__(self, event_queue, simulator, capacity):
            self.simulator = simulator

        def run(self):
            import pytest
            with pytest.raises(ValueError):
                self.simulator.start()
            assert not self.simulator.is_active()
            assert self.simulator.metrics is None

    monkeypatch.setattr(entry, "ParkingApp", FakeApp)
    entry.main()


def test_app_error_is_audited_before_shutdown_and_close(monkeypatch, tmp_path, capsys):
    from simulation.audit_logging import AuditSession

    error = RuntimeError("application failed")
    cleanup_error = ValueError("shutdown failed")
    close_error = OSError("close failed")
    audit = AuditSession(tmp_path / "logs")
    monkeypatch.setattr(entry, "AuditSession", lambda: audit)
    order = []

    class FakeSimulator:
        def __init__(self, **kwargs):
            pass

        def set_audit(self, session):
            assert session is audit

        def shutdown(self):
            order.append("shutdown")
            raise cleanup_error

    original_close = audit.close

    def tracked_close():
        order.append("close")
        original_close()
        content = audit.path.read_text(encoding="utf-8")
        assert "exception_type=RuntimeError" in content
        assert audit._records.unfinished_tasks == 0
        raise close_error

    audit.close = tracked_close

    class FakeApp:
        def __init__(self, **kwargs):
            pass

        def run(self):
            raise error

    monkeypatch.setattr(entry, "Simulator", FakeSimulator)
    monkeypatch.setattr(entry, "ParkingApp", FakeApp)
    import pytest
    with pytest.raises(RuntimeError) as raised:
        entry.main()

    assert raised.value is error
    assert order == ["shutdown", "close"]
    content = audit.path.read_text(encoding="utf-8")
    assert content.count("exception_type=RuntimeError") == 1
    assert "application failed" in content
    assert "RuntimeError: application failed" in content
    assert content.count("exception_type=ValueError") == 1
    assert content.count("shutdown failed") == 1
    assert "close failed" in capsys.readouterr().err
    assert audit._records.unfinished_tasks == 0
