"""Grouped pending requests visualizer organized by authorized parking slot."""

from __future__ import annotations

import tkinter as tk

from ui.components.theme import (
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    COLOR_WAITING_BG,
    font_family,
)
from ui.projection import ParkingProjection


class WaitingQueueWidget(tk.Frame):
    """Compact view of requests currently waiting for their authorized slot.

    Reflects the project's actual scheduling policy: FIFO among eligible
    requests and strict FIFO per authorized slot. Displays only requests
    confirmed as waiting, in observed acceptance order, without deciding
    admission or replacing Core logic.
    """

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
            **kwargs,
        )
        self._vehicles: list[int] = []
        self._plates: dict[int, str] = {}
        self._authorized_slots: dict[int, int | None] = {}
        self._states: dict[int, str] = {}
        self._group_rows: dict[int | None, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        # Top Bar Header
        top_bar = tk.Frame(self, bg=COLOR_BG_CARD)
        top_bar.pack(fill="x")

        lbl_title = tk.Label(
            top_bar,
            text="SOLICITUDES PENDIENTES POR PUESTO AUTORIZADO (FIFO por puesto)",
            bg=COLOR_BG_CARD,
            fg=COLOR_WAITING,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        )
        lbl_title.pack(side="left")

        self._lbl_count = tk.Label(
            top_bar,
            text="0 pendientes",
            bg=COLOR_WAITING_BG,
            fg=COLOR_WAITING,
            font=(font_family(self), 8, "bold"),
            padx=6,
            pady=1,
        )
        self._lbl_count.pack(side="right")

        # Scrollable viewport (both vertical and horizontal) for slot groups
        viewport = tk.Frame(self, bg=COLOR_BG_CARD)
        viewport.pack(fill="both", expand=True, pady=(6, 0))

        self._canvas = tk.Canvas(
            viewport,
            bg=COLOR_BG_CARD,
            height=78,
            highlightthickness=0,
            bd=0,
        )
        self._vscroll = tk.Scrollbar(
            viewport,
            orient="vertical",
            command=self._canvas.yview,
        )
        self._scrollbar = tk.Scrollbar(
            viewport,
            orient="horizontal",
            command=self._canvas.xview,
        )
        self._canvas.configure(
            xscrollcommand=self._scrollbar.set,
            yscrollcommand=self._vscroll.set,
        )
        self._canvas.pack(side="left", fill="both", expand=True)

        # Inner container for grouped slot rows inside the canvas
        self._items_container = tk.Frame(self._canvas, bg=COLOR_BG_CARD)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._items_container, anchor="nw"
        )
        self._items_container.bind("<Configure>", self._on_items_configure)

        self._lbl_empty = tk.Label(
            self._items_container,
            text="No hay solicitudes pendientes de ingreso.",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9, "italic"),
        )
        self._items_container.grid_columnconfigure(0, weight=1)
        self._lbl_empty.grid(row=0, column=0, sticky="w", pady=4)

    def _on_items_configure(self, _event: tk.Event | None = None) -> None:
        """Update canvas scrollregion and toggle scrollbars when content overflows."""
        bbox = self._canvas.bbox("all")
        if bbox is not None:
            self._canvas.configure(scrollregion=bbox)
            content_width = bbox[2] - bbox[0]
            content_height = bbox[3] - bbox[1]
            canvas_width = max(self._canvas.winfo_width(), 1)
            canvas_height = max(self._canvas.winfo_height(), 1)
            if content_width > canvas_width and len(self._vehicles) > 1:
                if not self._scrollbar.winfo_ismapped():
                    self._scrollbar.pack(side="bottom", fill="x", pady=(2, 0))
            elif self._scrollbar.winfo_ismapped():
                self._scrollbar.pack_forget()
            if content_height > canvas_height and len(self._vehicles) > 1:
                if not self._vscroll.winfo_ismapped():
                    self._vscroll.pack(side="right", fill="y", padx=(2, 0))
            elif self._vscroll.winfo_ismapped():
                self._vscroll.pack_forget()

    def add_vehicle(
        self,
        vehicle_id: int,
        plate: str | None = None,
        authorized_slot: int | None = None,
        state: str = "WAITING",
    ) -> None:
        """Add or update a pending request preserving acceptance order."""
        if vehicle_id not in self._vehicles:
            self._vehicles.append(vehicle_id)
        if plate:
            self._plates[vehicle_id] = plate
        elif vehicle_id not in self._plates:
            self._plates[vehicle_id] = f"Auto #{vehicle_id}"
        if authorized_slot is not None or vehicle_id not in self._authorized_slots:
            self._authorized_slots[vehicle_id] = authorized_slot
        self._states[vehicle_id] = state
        self._refresh()

    def remove_vehicle(self, vehicle_id: int) -> None:
        """Remove request identity once it enters, cancels, or finishes."""
        if vehicle_id in self._vehicles:
            self._vehicles.remove(vehicle_id)
            self._plates.pop(vehicle_id, None)
            self._authorized_slots.pop(vehicle_id, None)
            self._states.pop(vehicle_id, None)
            self._refresh()

    def sync_from_projection(self, projection: ParkingProjection) -> None:
        """Synchronize only confirmed waiters from canonical projection state."""
        vehicles = [vid for vid in projection.pending_order if vid in projection.waiting]
        plates: dict[int, str] = {}
        authorized_slots: dict[int, int | None] = {}
        states: dict[int, str] = {}
        for vid in vehicles:
            rec = projection.requests.get(vid)
            if rec is not None:
                plates[vid] = rec.plate or f"Auto #{vid}"
                authorized_slots[vid] = rec.authorized_slot
                states[vid] = rec.state
            else:
                plates[vid] = f"Auto #{vid}"
                authorized_slots[vid] = None
                states[vid] = "WAITING"
        if (vehicles == self._vehicles and plates == self._plates
                and authorized_slots == self._authorized_slots and states == self._states):
            return
        self._vehicles = vehicles
        self._plates = plates
        self._authorized_slots = authorized_slots
        self._states = states
        self._refresh()

    def grouped_pending(self) -> dict[int | None, list[int]]:
        """Return pending vehicle IDs grouped by 1-based authorized slot in acceptance order."""
        groups: dict[int | None, list[int]] = {}
        for vid in self._vehicles:
            slot = self._authorized_slots.get(vid)
            groups.setdefault(slot, []).append(vid)
        return groups

    def clear(self) -> None:
        """Clear all pending requests."""
        self._vehicles.clear()
        self._plates.clear()
        self._authorized_slots.clear()
        self._states.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Update a bounded set of per-slot rows without rebuilding the view."""
        count = len(self._vehicles)
        self._lbl_count.config(
            text=f"{count} pendiente{'s' if count != 1 else ''}"
        )

        groups = self.grouped_pending()
        for slot_key, (row, _, _) in self._group_rows.items():
            if slot_key not in groups:
                row.grid_remove()

        if not groups:
            self._lbl_empty.grid()
            self._canvas.xview_moveto(0.0)
            self._canvas.yview_moveto(0.0)
            self._on_items_configure()
            return

        self._lbl_empty.grid_remove()
        # Sort group rows by slot number (1..N, then None) while keeping acceptance order inside each group
        sorted_slots = sorted(
            groups.keys(), key=lambda s: (s is None, s if s is not None else 0)
        )

        for row_index, slot_key in enumerate(sorted_slots):
            vids = groups[slot_key]
            row_data = self._group_rows.get(slot_key)
            if row_data is None:
                group_row = tk.Frame(self._items_container, bg=COLOR_BG_CARD)
                slot_label = tk.Label(
                    group_row,
                    text="",
                    width=11,
                    anchor="w",
                    bg=COLOR_BG_PRIMARY,
                    fg=COLOR_INFO,
                    font=(font_family(self), 8, "bold"),
                    padx=6,
                    pady=3,
                )
                slot_label.pack(side="left", padx=(0, 6))
                queue_label = tk.Label(
                    group_row,
                    text="",
                    anchor="w",
                    bg=COLOR_BG_CARD,
                    fg=COLOR_TEXT_PRIMARY,
                    font=(font_family(self), 8),
                )
                queue_label.pack(side="left", fill="x", expand=True)
                row_data = (group_row, slot_label, queue_label)
                self._group_rows[slot_key] = row_data

            group_row, slot_label, queue_label = row_data
            slot_label.config(text=f"Puesto #{slot_key}:" if slot_key is not None else "Puesto s/a:")
            preview = [self._plates.get(vid, f"Auto #{vid}") for vid in vids[:3]]
            queue_text = f"{len(vids)} en espera: " + " → ".join(preview)
            if len(vids) > len(preview):
                queue_text += f" · +{len(vids) - len(preview)} más"
            queue_label.config(text=queue_text)
            group_row.grid(row=row_index, column=0, sticky="ew", pady=2)

        self._on_items_configure()


__all__ = ["WaitingQueueWidget"]
