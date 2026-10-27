"""Parking bay slot and lot grid visual components."""

from __future__ import annotations

import tkinter as tk
from typing import Iterable

from ui.components.theme import (
    CAR_OCCUPIED_ICON_PATH,
    COLOR_AVAILABLE,
    COLOR_AVAILABLE_BG,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_OCCUPIED,
    COLOR_OCCUPIED_BG,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    PARKING_SPACE_ICON_PATH,
    _load_png_icon,
    font_family,
)
from ui.projection import project_occupied_spaces


class ParkingSlotWidget(tk.Frame):
    """Graphical representation of a single parking bay / space.

    In OS terms, each slot represents a discrete shared resource unit
    with mutual exclusion: at most one vehicle can occupy it at any time.
    """

    def __init__(self, parent: tk.Widget, space_id: int, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=2,
            padx=8,
            pady=10,
            **kwargs,
        )
        self.space_id = space_id
        self.occupied_by: int | None = None
        self.plate: str | None = None
        self._img_available = _load_png_icon(self, PARKING_SPACE_ICON_PATH, subsample=2)
        self._img_occupied = _load_png_icon(self, CAR_OCCUPIED_ICON_PATH, subsample=2)
        self._has_icons = (
            self._img_available is not None and self._img_occupied is not None
        )

        # Space Identifier (e.g., Espacio #1)
        self._lbl_id = tk.Label(
            self,
            text=f"Espacio #{space_id}",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9, "bold"),
        )
        self._lbl_id.pack(anchor="center")

        # Slot Icon: uses 48x48 PNG assets when present, falling back to fixed-width ASCII.
        if self._has_icons:
            self._lbl_icon = tk.Label(
                self,
                image=self._img_available,
                text="",
                bg=COLOR_BG_CARD,
                fg=COLOR_TEXT_PRIMARY,
            )
        else:
            self._lbl_icon = tk.Label(
                self,
                text="P",
                width=5,
                bg=COLOR_BG_CARD,
                fg=COLOR_TEXT_PRIMARY,
                font=(font_family(self), 16, "bold"),
            )
        self._lbl_icon.pack(anchor="center", pady=(4, 2))

        # Status Badge (DISPONIBLE / OCUPADO) with compact fixed width to avoid layout jitter
        self._lbl_status = tk.Label(
            self,
            text="DISPONIBLE",
            width=10,
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
            font=(font_family(self), 8, "bold"),
            padx=4,
            pady=2,
        )
        self._lbl_status.pack(anchor="center", pady=(4, 0))

        # Vehicle Details with compact fixed width so 5 columns fit alongside the Event Log
        self._lbl_detail = tk.Label(
            self,
            text="Libre",
            width=13,
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
        )
        self._lbl_detail.pack(anchor="center", pady=(2, 0))

    def set_occupied(self, vehicle_id: int, plate: str | None = None) -> None:
        """Mark slot as occupied by a vehicle request."""
        self.occupied_by = vehicle_id
        self.plate = plate
        self.config(highlightbackground=COLOR_OCCUPIED, highlightthickness=2)
        if self._has_icons:
            self._lbl_icon.config(image=self._img_occupied, text="")
        else:
            self._lbl_icon.config(text="AUTO")
        self._lbl_status.config(
            text="OCUPADO",
            bg=COLOR_OCCUPIED_BG,
            fg=COLOR_OCCUPIED,
        )
        self._lbl_detail.config(
            text=f"{plate} (#{vehicle_id})" if plate else f"Auto #{vehicle_id}",
            fg=COLOR_TEXT_PRIMARY,
        )

    def set_available(self) -> None:
        """Mark slot as free when the vehicle leaves."""
        self.occupied_by = None
        self.plate = None
        self.config(highlightbackground=COLOR_BORDER, highlightthickness=2)
        if self._has_icons:
            self._lbl_icon.config(image=self._img_available, text="")
        else:
            self._lbl_icon.config(text="P")
        self._lbl_status.config(
            text="DISPONIBLE",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
        )
        self._lbl_detail.config(
            text="Libre",
            fg=COLOR_TEXT_MUTED,
        )

    def reset(self) -> None:
        """Reset slot back to available state."""
        self.set_available()


class ParkingLotGridWidget(tk.Frame):
    """Container grid organizing all parking slot widgets."""

    def __init__(self, parent: tk.Widget, columns: int = 5, **kwargs) -> None:
        super().__init__(parent, bg=COLOR_BG_PRIMARY, **kwargs)
        self.columns = columns
        self.slots: dict[int, ParkingSlotWidget] = {}

    def setup_slots(self, capacity: int) -> None:
        """Instantiate slot widgets based on configured parking capacity."""
        for slot in self.slots.values():
            slot.destroy()
        self.slots.clear()

        total_rows = max(1, (capacity + self.columns - 1) // self.columns)
        for index in range(1, capacity + 1):
            row = (index - 1) // self.columns
            col = (index - 1) % self.columns
            slot_widget = ParkingSlotWidget(self, space_id=index)
            slot_widget.grid(row=row, column=col, padx=5, pady=5, sticky="ew")
            self.slots[index] = slot_widget

        for col_idx in range(self.columns):
            self.grid_columnconfigure(col_idx, weight=1, uniform="slot_col")
        for row_idx in range(total_rows):
            # Keep natural card height so slots do not stretch into tall empty towers on maximize
            self.grid_rowconfigure(row_idx, weight=0)

    def occupy_slot(self, slot_key: int, vehicle_id: int, plate: str | None = None) -> None:
        """Mark a projected, 1-based display slot as occupied."""
        self.slots[slot_key].set_occupied(vehicle_id, plate)

    def free_slot(self, slot_key: int) -> None:
        """Free a projected, 1-based display slot."""
        self.slots[slot_key].set_available()

    def sync_from_snapshot(self, occupied_spaces: Iterable[tuple[int, int]]) -> None:
        """Translate raw core snapshot pairs once, then render display slots."""
        self.render_occupied(project_occupied_spaces(occupied_spaces, len(self.slots)))

    def render_occupied(
        self,
        occupied: dict[int, int],
        plates: dict[int, str] | None = None,
    ) -> None:
        """Render already-projected keys, clearing slots absent from the mapping.

        `plates` maps vehicle IDs to plates so reconciliation keeps them visible.
        """
        if any(key not in self.slots for key in occupied):
            raise ValueError("Projected slot is not present in the grid")
        plates = plates or {}
        for key, slot in self.slots.items():
            if key in occupied:
                slot.set_occupied(occupied[key], plates.get(occupied[key]))
            else:
                slot.set_available()

    def reset(self) -> None:
        """Reset all slots to available."""
        for slot in self.slots.values():
            slot.reset()


__all__ = ["ParkingLotGridWidget", "ParkingSlotWidget"]
