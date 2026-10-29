"""Composition test without constructing a Tk root."""

from queue import Queue

from simulation.authorizations import Authorization, AuthorizationRegistry

import main as entry


def test_main_composes_ipc_controller_with_validated_payload(monkeypatch, tmp_path):
    from simulation.audit_logging import AuditSession
    monkeypatch.setattr(entry, "AuditSession", lambda: AuditSession(tmp_path / "logs"))
    monkeypatch.setattr(entry.config, "PLATE_SEQUENCE", ("EDU-001", "EDU-002"))
    monkeypatch.setattr(entry, "load_authorizations", lambda *_: AuthorizationRegistry({
        "EDU-001": Authorization("EDU-001", True, 0),
    }))
    observed = {}

    class FakeController:
        def __init__(self, capacity, audit, supported_capacities):
            observed.update(
                capacity=capacity,
                audit=audit,
                supported_capacities=supported_capacities,
            )

    class FakeAdapter:
        def __init__(self, controller, event_queue, payload_factory):
            observed.update(
                controller=controller,
                queue=event_queue,
                payload_factory=payload_factory,
                payload=payload_factory(),
            )
            self.metrics = None
            self.shutdown_complete = True
            self.error = None
        def start_engine(self): pass
        def shutdown_async(self): pass

    class FakeApp:
        def __init__(self, event_queue, simulator, capacity,
                     scenario_options, on_scenario_selected):
            assert event_queue is observed["queue"]
            assert capacity == observed["capacity"]
            assert set(scenario_options) == {
                "authorization_rejections",
                "capacity_saturation_and_release",
                "normal_entry_and_exit",
            }
            on_scenario_selected("normal_entry_and_exit")
            observed["selected_payload"] = observed["payload_factory"]()
        def run(self): pass

    monkeypatch.setattr(entry, "MultiprocessController", FakeController)
    monkeypatch.setattr(entry, "MultiprocessGUIAdapter", FakeAdapter)
    monkeypatch.setattr(entry, "ParkingApp", FakeApp)
    entry.main()
    assert observed["payload"]["plate_sequence"] == [
        "OND-830", "BZO-132", "NGX-553", "OND-830", "CWR-850",
    ]
    assert observed["payload"]["config"]["capacity"] == 6
    assert observed["selected_payload"]["config"]["capacity"] == 6
    assert observed["supported_capacities"] == {6}


def test_main_without_run_does_not_print_statistics(monkeypatch, capsys, tmp_path):
    from simulation.audit_logging import AuditSession
    monkeypatch.setattr(entry, "AuditSession", lambda: AuditSession(tmp_path / "logs"))
    class FakeApp:
        def __init__(self, event_queue, simulator, capacity, **_kwargs):
            pass

        def run(self):
            pass

    class FakeAdapter:
        metrics = None
        shutdown_complete = True
        error = None
        def __init__(self, *args): pass
        def start_engine(self): pass
        def shutdown_async(self): pass
    monkeypatch.setattr(entry, "MultiprocessController", lambda *args, **kwargs: object())
    monkeypatch.setattr(entry, "MultiprocessGUIAdapter", FakeAdapter)
    monkeypatch.setattr(entry, "ParkingApp", FakeApp)
    entry.main()
    assert capsys.readouterr().out == ""


def test_invalid_authorization_file_prevents_controller_start(monkeypatch, tmp_path):
    from simulation.audit_logging import AuditSession
    monkeypatch.setattr(entry, "AuditSession", lambda: AuditSession(tmp_path / "logs"))
    bad_file = tmp_path / "invalid.json"
    bad_file.write_text('{"vehicles": [}', encoding="utf-8")
    monkeypatch.setattr(entry.config, "AUTHORIZATION_FILE", bad_file)
    monkeypatch.setattr(entry.config, "PLATE_SEQUENCE", ("A",))

    import pytest
    with pytest.raises(ValueError):
        entry.main()


def test_app_error_is_audited_before_shutdown_and_close(monkeypatch, tmp_path, capsys):
    from simulation.audit_logging import AuditSession

    error = RuntimeError("application failed")
    cleanup_error = ValueError("shutdown failed")
    close_error = OSError("close failed")
    audit = AuditSession(tmp_path / "logs")
    monkeypatch.setattr(entry, "AuditSession", lambda: audit)
    order = []

    class FakeAdapter:
        metrics = None
        shutdown_complete = False
        error = cleanup_error
        def __init__(self, *args): pass
        def start_engine(self): pass
        def shutdown_async(self): order.append("shutdown")
        class Thread:
            def join(self): pass
        _thread = Thread()

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

    monkeypatch.setattr(entry, "MultiprocessController", lambda *args, **kwargs: object())
    monkeypatch.setattr(entry, "MultiprocessGUIAdapter", FakeAdapter)
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
