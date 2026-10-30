"""Tests for retained occupancy-series behavior and the telemetry dashboard."""

from types import SimpleNamespace
from queue import Queue

from core.events import ParkingEvent
from ui.interface import ParkingApp
from ui.components.telemetry_bars import OccupancySeries


def event(kind, timestamp, vehicle_id=None, space_id=None):
    return SimpleNamespace(
        type=kind, timestamp=timestamp, vehicle_id=vehicle_id, space_id=space_id
    )


def test_series_starts_at_zero_and_tracks_step_values_from_real_events():
    series = OccupancySeries(capacity=2)

    assert series.points == [(None, 0)]
    assert series.record(event("VEHICLE_ENTERED", 10.0, 1, 0)) is True
    assert series.record(event("VEHICLE_ENTERED", 12.0, 2, 1)) is True
    assert series.record(event("VEHICLE_EXITED", 15.0, 1, 0)) is True
    assert series.points == [(None, 0), (10.0, 1), (12.0, 2), (15.0, 1)]
    assert series.occupancy == 1


def test_series_rejects_inconsistent_transitions_without_changing_occupancy():
    series = OccupancySeries(capacity=1)
    assert series.record(event("VEHICLE_EXITED", 10.0, 1, 0)) is False
    assert series.warning
    assert series.occupancy == 0
    assert series.record(event("VEHICLE_ENTERED", 11.0, 1, 0)) is True
    assert series.record(event("VEHICLE_ENTERED", 12.0, 2, 1)) is False
    assert series.occupancy == 1
    assert series.record(event("VEHICLE_EXITED", 13.0, 1, 1)) is False
    assert series.occupancy == 1


def test_series_resets_between_runs_and_bounds_work_for_large_histories():
    series = OccupancySeries(capacity=1)
    for index in range(5000):
        assert series.record(event("VEHICLE_ENTERED", index * 2, index, 0))
        assert series.record(event("VEHICLE_EXITED", index * 2 + 1, index, 0))

    assert len(series.points) == 10001
    series.reset(1)
    assert series.points == [(None, 0)]
    assert series.occupancy == 0
    assert not series.warning


def test_dashboard_lifecycle_keeps_each_run_separate_and_marks_stop_state():
    app = ParkingApp(event_queue=Queue(), capacity=2)
    try:
        assert "SIN EJECUCIÓN" in app._telemetry_status.cget("text")
        app._dispatch_event(ParkingEvent("SIMULATION_STARTED", 100.0))
        app._dispatch_event(ParkingEvent("VEHICLE_ENTERED", 101.0, 1, 0))
        app._dispatch_event(ParkingEvent("VEHICLE_EXITED", 102.0, 1, 0))
        app._dispatch_event(ParkingEvent("VEHICLE_CANCELLED", 103.0, 2))
        app._dispatch_event(ParkingEvent("SIMULATION_FINISHED", 104.0))
        assert app.card_telemetry_current.value == "0"
        assert app.card_peak_occupancy.value == "1"
        assert "DETENIDA" in app._telemetry_status.cget("text")

        app._dispatch_event(ParkingEvent("SIMULATION_STARTED", 200.0))
        assert app.card_telemetry_current.value == "0"
        assert app.card_peak_occupancy.value == "0"
        assert "EN EJECUCIÓN" in app._telemetry_status.cget("text")
        app._dispatch_event(ParkingEvent("SIMULATION_FINISHED", 204.0))
        assert "FINALIZADA" in app._telemetry_status.cget("text")
    finally:
        app.root.destroy()


def test_dashboard_keeps_three_by_two_kpis_and_reflows_panels_at_narrow_widths():
    app = ParkingApp(event_queue=Queue(), capacity=5)
    try:
        app._relayout_telemetry_kpis(SimpleNamespace(width=500))
        assert app._telemetry_kpi_cards == [
            app.card_generated,
            app.card_accepted,
            app.card_rejected,
            app.card_entries,
            app.card_finished,
            app.card_cancelled,
        ]
        assert [card.grid_info()["row"] for card in app._telemetry_kpi_cards] == [
            0, 0, 0, 1, 1, 1
        ]
        assert not hasattr(app, "telemetry_utilization_label")
        assert app.telemetry_capacity_panel.cget("pady") == 8
        assert app.card_avg_wait.grid_info()["pady"] == 2
        app._relayout_telemetry_content(SimpleNamespace(width=600))
        assert not hasattr(app, "occupancy_chart")
        assert app.telemetry_capacity_panel.grid_info()["row"] == 0
        assert app.telemetry_performance_panel.grid_info()["row"] == 1

        app._relayout_telemetry_content(SimpleNamespace(width=1000))
        assert app.telemetry_capacity_panel.grid_info()["column"] == 0
        assert app.telemetry_performance_panel.grid_info()["column"] == 1
    finally:
        app.root.destroy()
