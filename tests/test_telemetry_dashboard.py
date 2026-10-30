"""Dashboard B presentation tests without changing the original chart tests."""

from types import SimpleNamespace

from ui.interface import ParkingApp


class RecordingCard:
    def __init__(self):
        self.value = None
        self.subtitle = None
        self.grid_options = {}

    def update_value(self, value, subtitle=None):
        self.value = str(value)
        if subtitle is not None:
            self.subtitle = subtitle

    def update_subtitle(self, subtitle):
        self.subtitle = subtitle

    def grid(self, **options):
        self.grid_options = options


class RecordingContainer:
    def __init__(self):
        self.columns = {}

    def grid_columnconfigure(self, column, **options):
        self.columns[column] = options


class RecordingProgress:
    def __init__(self):
        self.value = None

    def configure(self, **options):
        self.value = options["value"]


def make_dashboard_app(capacity=5, peak=0, occupied=0):
    app = object.__new__(ParkingApp)
    app.capacity = capacity
    app.projection = SimpleNamespace(occupied_count=occupied)
    app._telemetry_kpis = RecordingContainer()
    app._telemetry_kpi_cards = [RecordingCard() for _ in range(6)]
    app.card_telemetry_current = RecordingCard()
    app.card_telemetry_capacity = RecordingCard()
    app.card_peak_occupancy = RecordingCard()
    app.card_max_utilization = RecordingCard()
    app.card_peak_waiting = RecordingCard()
    app.card_avg_wait = RecordingCard()
    app.card_avg_parking = RecordingCard()
    app.card_duration = RecordingCard()
    app.telemetry_utilization_bar = RecordingProgress()
    app._update_telemetry_metrics({
        "peak_occupancy": peak,
        "peak_waiting": 0,
        "average_waiting_time": 0,
        "average_parking_time": 0,
        "total_duration": None,
    })
    return app


def test_telemetry_kpis_stay_in_three_columns_and_two_rows_at_any_width():
    app = make_dashboard_app()

    for width in (420, 620, 1200):
        app._relayout_telemetry_kpis(SimpleNamespace(width=width))
        assert [(card.grid_options["row"], card.grid_options["column"])
                for card in app._telemetry_kpi_cards] == [
            (0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2),
        ]


def test_telemetry_panels_stack_narrow_and_share_width_when_wide():
    app = object.__new__(ParkingApp)
    app._telemetry_content = RecordingContainer()
    app.telemetry_capacity_panel = RecordingCard()
    app.telemetry_performance_panel = RecordingCard()

    app._relayout_telemetry_content(SimpleNamespace(width=600))
    assert app.telemetry_capacity_panel.grid_options["row"] == 0
    assert app.telemetry_performance_panel.grid_options["row"] == 1
    assert app.telemetry_capacity_panel.grid_options["columnspan"] == 2

    app._relayout_telemetry_content(SimpleNamespace(width=1000))
    assert app.telemetry_capacity_panel.grid_options["row"] == 0
    assert app.telemetry_capacity_panel.grid_options["column"] == 0
    assert app.telemetry_performance_panel.grid_options["column"] == 1


def test_capacity_panel_distinguishes_current_peak_and_uses_peak_for_utilization():
    app = make_dashboard_app(capacity=6, peak=4, occupied=2)

    app._update_telemetry_metrics({
        "peak_occupancy": 4,
        "peak_waiting": 3,
        "average_waiting_time": 1.25,
        "average_parking_time": 8.5,
        "total_duration": 30.0,
    })

    assert app.card_telemetry_current.value == "2"
    assert app.card_telemetry_capacity.value == "6"
    assert app.card_peak_occupancy.value == "4"
    assert app.card_peak_occupancy.subtitle is None
    assert app.card_max_utilization.value == "66.7%"
    assert app.telemetry_utilization_bar.value == 66.66666666666666
    assert app.card_peak_waiting.value == "3"
    assert app.card_avg_wait.value == "1.25s"
    assert app.card_avg_parking.value == "8.50s"
    assert app.card_duration.value == "30.00s"


def test_capacity_panel_handles_zero_capacity_and_live_duration():
    app = make_dashboard_app(capacity=0, peak=0, occupied=0)

    app._update_telemetry_metrics({
        "peak_occupancy": 0,
        "peak_waiting": 0,
        "average_waiting_time": None,
        "average_parking_time": None,
        "total_duration": None,
    })

    assert app.card_max_utilization.value == "0.0%"
    assert app.telemetry_utilization_bar.value == 0
    assert app.card_duration.value == "N/D"
