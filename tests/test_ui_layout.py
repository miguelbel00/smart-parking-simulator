"""Headless boundary tests for compact parking and waiting-lane layouts."""

from ui.widgets import ParkingLotGridWidget, waiting_queue_preview


def test_hundred_spaces_form_ten_rows_in_two_banks_with_clear_outer_bounds() -> None:
    bounds = [ParkingLotGridWidget.slot_bounds(space_id) for space_id in range(1, 101)]

    assert len(set(bounds)) == 100
    assert bounds[0][1] == bounds[9][1]
    assert bounds[9][1] < bounds[10][1]
    assert bounds[0][0] < bounds[5][0]
    assert bounds[94][1] == bounds[99][1]
    assert bounds[99][1] == bounds[0][1] + 9 * ParkingLotGridWidget.ROW_HEIGHT


def test_small_capacity_uses_the_same_one_based_layout() -> None:
    assert ParkingLotGridWidget.slot_bounds(1) != ParkingLotGridWidget.slot_bounds(2)
    assert ParkingLotGridWidget.slot_bounds(11)[1] > ParkingLotGridWidget.slot_bounds(1)[1]


def test_slot_update_methods_handle_the_hundredth_space_headlessly() -> None:
    class CanvasStub:
        def __init__(self) -> None:
            self.updates = []

        def itemconfigure(self, item_id, **options) -> None:
            self.updates.append((item_id, options))

    grid = object.__new__(ParkingLotGridWidget)
    grid.slots = {100: {"rect": 1, "label": 2, "detail": 3}}
    grid.canvas = CanvasStub()

    grid.occupy_slot(100, 200)
    assert grid.canvas.updates[-1][1]["text"] == "Auto #200"
    grid.free_slot(100)
    assert grid.canvas.updates[-1][1]["text"] == "LIBRE"


def test_snapshot_space_zero_maps_to_visible_slot_one() -> None:
    class CanvasStub:
        def __init__(self) -> None:
            self.updates = []

        def itemconfigure(self, item_id, **options) -> None:
            self.updates.append((item_id, options))

    grid = object.__new__(ParkingLotGridWidget)
    grid.slots = {1: {"rect": 1, "label": 2, "detail": 3}}
    grid.canvas = CanvasStub()

    grid.sync_from_snapshot(((0, 42),))

    assert grid.canvas.updates[-1][1]["text"] == "Auto #42"


def test_waiting_preview_shows_first_five_and_overflow_but_keeps_input() -> None:
    waiting_ids = list(range(1, 31))

    assert waiting_queue_preview(waiting_ids) == "#1  ·  #2  ·  #3  ·  #4  ·  #5  ·  +25 más"
    assert len(waiting_ids) == 30


def test_waiting_preview_handles_no_overflow() -> None:
    assert waiting_queue_preview([11, 12]) == "#11  ·  #12"
