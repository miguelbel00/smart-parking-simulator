"""Headless boundary tests for the top-down parking and waiting-lane layouts."""

from ui.widgets import ParkingLotGridWidget, diagram_font_size, diagram_transform, waiting_queue_preview


def test_diagram_scales_uniformly_and_centers_in_wide_viewport() -> None:
    scale, offset_x, offset_y = diagram_transform(500, 400, 900, 700)

    assert scale == 1.75
    assert offset_x == 12.5
    assert offset_y == 0


def test_tall_diagram_remains_width_scaled_for_vertical_scrolling() -> None:
    scale, offset_x, _ = diagram_transform(500, 1800, 900, 700, allow_vertical_scroll=True)

    assert scale == 1.8
    assert offset_x == 0


def test_scaled_diagram_font_respects_minimum_size() -> None:
    assert diagram_font_size(13, 0.5) == 8
    assert diagram_font_size(13, 1.5) == 20


def test_hundred_spaces_form_ten_top_bottom_pairs_with_unique_bounds() -> None:
    bounds = [ParkingLotGridWidget.slot_bounds(space_id) for space_id in range(1, 101)]

    assert len(set(bounds)) == 100
    assert bounds[0][1] == bounds[4][1]
    assert bounds[0][1] < bounds[5][1]
    assert bounds[5][1] == bounds[9][1]
    assert bounds[0][0] < bounds[4][0]
    assert bounds[90][1] == bounds[94][1]
    assert bounds[95][1] == bounds[99][1]
    assert bounds[90][1] == bounds[0][1] + 9 * (
        2 * ParkingLotGridWidget.ROW_HEIGHT + ParkingLotGridWidget.AISLE_HEIGHT
    )


def test_small_capacity_uses_the_same_one_based_layout() -> None:
    assert ParkingLotGridWidget.slot_bounds(1) != ParkingLotGridWidget.slot_bounds(2)
    assert ParkingLotGridWidget.slot_bounds(11)[1] > ParkingLotGridWidget.slot_bounds(6)[1]


def test_ten_spaces_form_top_and_bottom_banks_around_horizontal_aisle() -> None:
    top_bank = [ParkingLotGridWidget.slot_bounds(space_id) for space_id in range(1, 6)]
    bottom_bank = [ParkingLotGridWidget.slot_bounds(space_id) for space_id in range(6, 11)]

    assert len({bounds[1] for bounds in top_bank}) == 1
    assert len({bounds[1] for bounds in bottom_bank}) == 1
    assert top_bank[0][0] < top_bank[-1][0]
    assert bottom_bank[0][0] < bottom_bank[-1][0]
    assert bottom_bank[0][1] - top_bank[0][3] == ParkingLotGridWidget.AISLE_HEIGHT + 4


def test_odd_capacity_keeps_each_space_inside_a_bank() -> None:
    bounds = [ParkingLotGridWidget.slot_bounds(space_id) for space_id in range(1, 12)]

    assert len(set(bounds)) == 11
    assert bounds[10][1] > bounds[0][1]


def test_canvas_scroll_region_contains_both_banks() -> None:
    class CanvasStub:
        def __init__(self) -> None:
            self.scrollregion = None
            self.next_item_id = 0
            self.text_items = []

        def delete(self, _tag) -> None:
            pass

        def create_rectangle(self, *_args, **_kwargs) -> int:
            self.next_item_id += 1
            return self.next_item_id

        def create_line(self, *_args, **_kwargs) -> int:
            self.next_item_id += 1
            return self.next_item_id

        def create_text(self, *_args, **_kwargs) -> int:
            self.next_item_id += 1
            self.text_items.append(self.next_item_id)
            return self.next_item_id

        def create_polygon(self, *_args, **_kwargs) -> int:
            self.next_item_id += 1
            return self.next_item_id

        def configure(self, **options) -> None:
            self.scrollregion = options.get("scrollregion", self.scrollregion)

        def addtag_withtag(self, *_args) -> None:
            pass

        def find_withtag(self, tag) -> tuple[int, ...]:
            return tuple(self.text_items) if tag == "diagram_text" else ()

        def itemconfigure(self, *_args, **_kwargs) -> None:
            pass

        def winfo_width(self) -> int:
            return 600

        def winfo_height(self) -> int:
            return 500

        def scale(self, *_args) -> None:
            pass

        def move(self, *_args) -> None:
            pass

    grid = object.__new__(ParkingLotGridWidget)
    grid.columns = 5
    grid.slots = {}
    grid._content_size = (0, 0)
    grid._allow_vertical_scroll = False
    grid._render_scale = 1.0
    grid._render_x = 0.0
    grid._render_y = 0.0
    grid._text_base_sizes = {}
    grid.canvas = CanvasStub()

    grid.setup_slots(10)

    assert grid.canvas.scrollregion[3] >= max(
        ParkingLotGridWidget.slot_bounds(space_id)[3] for space_id in range(1, 11)
    )


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
