"""Headless checks for the current card-based parking-grid layout."""

from ui.components import parking_grid


class SlotStub:
    def __init__(self, parent, space_id: int) -> None:
        self.parent = parent
        self.space_id = space_id
        self.grid_options = None
        self.destroyed = False

    def grid(self, **options) -> None:
        self.grid_options = options

    def destroy(self) -> None:
        self.destroyed = True


def make_grid(monkeypatch, columns: int = 5):
    monkeypatch.setattr(parking_grid, "ParkingSlotWidget", SlotStub)
    grid = object.__new__(parking_grid.ParkingLotGridWidget)
    grid.columns = columns
    grid.slots = {}
    grid.column_configuration = []
    grid.row_configuration = []
    grid.grid_columnconfigure = lambda column, **options: grid.column_configuration.append(
        (column, options)
    )
    grid.grid_rowconfigure = lambda row, **options: grid.row_configuration.append(
        (row, options)
    )
    return grid


def test_capacity_slots_are_placed_in_row_major_grid(monkeypatch) -> None:
    grid = make_grid(monkeypatch)

    grid.setup_slots(11)

    assert list(grid.slots) == list(range(1, 12))
    assert [
        (slot.grid_options["row"], slot.grid_options["column"])
        for slot in grid.slots.values()
    ] == [
        (0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
        (1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (2, 0),
    ]
    assert [column for column, _ in grid.column_configuration] == list(range(5))
    assert [row for row, _ in grid.row_configuration] == [0, 1, 2]


def test_rebuilding_capacity_destroys_old_slots_and_replaces_them(monkeypatch) -> None:
    grid = make_grid(monkeypatch)
    grid.setup_slots(3)
    previous_slots = tuple(grid.slots.values())

    grid.setup_slots(2)

    assert all(slot.destroyed for slot in previous_slots)
    assert list(grid.slots) == [1, 2]
    assert all(slot.parent is grid for slot in grid.slots.values())


def test_empty_capacity_keeps_one_configurable_row(monkeypatch) -> None:
    grid = make_grid(monkeypatch)

    grid.setup_slots(0)

    assert grid.slots == {}
    assert grid.row_configuration == [(0, {"weight": 0})]
