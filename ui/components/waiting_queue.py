"""Grouped pending requests visualizer organized by authorized parking slot."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont

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
        self._group_rows: dict[
            int | None,
            tuple[
                tk.Frame, tk.Label, tk.Label, tk.Frame,
                dict[int, tk.Label], dict[int, tk.Label], list[int],
            ],
        ] = {}
        self._chip_font = tkfont.Font(
            root=self, family=font_family(self), size=11, weight="normal"
        )
        font_unit = max(self._chip_font.measure("0"), 1)
        typical_plate_width = self._chip_font.measure("WWW-888")
        self._chip_base_width = max(
            1, math.ceil(typical_plate_width / font_unit)
        )
        # Top Bar Header
        top_bar = tk.Frame(self, bg=COLOR_BG_CARD)
        top_bar.pack(fill="x")

        self._lbl_title = tk.Label(
            top_bar,
            text="Solicitudes pendientes",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 12, "bold"),
            anchor="w",
        )
        self._lbl_title.pack(side="left")

        self._lbl_count = tk.Label(
            top_bar,
            text="0 pendientes",
            bg=COLOR_WAITING_BG,
            fg=COLOR_WAITING,
            font=(font_family(self), 8, "bold"),
            padx=6,
            pady=1,
        )
        self._lbl_count.pack(side="right", padx=(8, 0))

        self._lbl_subtitle = tk.Label(
            self,
            text="FIFO por espacio autorizado",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 10),
            anchor="w",
        )
        self._lbl_subtitle.pack(fill="x", pady=(2, 0))

        # Scrollable viewport (both vertical and horizontal) for slot groups
        viewport = tk.Frame(self, bg=COLOR_BG_CARD)
        viewport.pack(fill="both", expand=True, pady=(6, 0))

        self._canvas = tk.Canvas(
            viewport,
            bg=COLOR_BG_CARD,
            height=112,
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
            if content_width > canvas_width:
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
        """Clear pending requests and reset chip sizing for a new run."""
        self._vehicles.clear()
        self._plates.clear()
        self._authorized_slots.clear()
        self._states.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Incrementally reconcile visible rows and chips with pending requests."""
        count = len(self._vehicles)
        total_text = f"{count} pendiente{'s' if count != 1 else ''}"
        if self._lbl_count.cget("text") != total_text:
            self._lbl_count.config(text=total_text)

        groups = self.grouped_pending()
        font_unit = max(self._chip_font.measure("0"), 1)

        for slot_key, row_data in self._group_rows.items():
            if slot_key in groups:
                continue
            row, _, _, _, chips, separators, rendered_order = row_data
            for chip in chips.values():
                chip.destroy()
            chips.clear()
            for separator in separators.values():
                separator.destroy()
            separators.clear()
            rendered_order.clear()
            if row.winfo_manager() == "grid":
                row.grid_remove()

        if not groups:
            if self._lbl_empty.winfo_manager() != "grid":
                self._lbl_empty.grid()
            self._canvas.xview_moveto(0.0)
            self._canvas.yview_moveto(0.0)
            self._on_items_configure()
            return

        if self._lbl_empty.winfo_manager() == "grid":
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
                    font=(font_family(self), 11, "bold"),
                    padx=8,
                    pady=5,
                )
                slot_label.pack(side="left", padx=(0, 8))
                count_label = tk.Label(
                    group_row, text="", anchor="w",
                    bg=COLOR_BG_CARD, fg=COLOR_WAITING,
                    font=(font_family(self), 9, "bold"),
                )
                count_label.pack(side="left", padx=(0, 8))
                plates_container = tk.Frame(group_row, bg=COLOR_BG_CARD)
                plates_container.pack(side="left", fill="x", expand=True)
                row_data = (
                    group_row, slot_label, count_label, plates_container, {}, {}, []
                )
                self._group_rows[slot_key] = row_data

            (
                group_row, slot_label, count_label, plates_container,
                chips, separators, rendered_order,
            ) = row_data
            slot_text = f"Espacio #{slot_key}" if slot_key is not None else "Espacio s/a"
            if slot_label.cget("text") != slot_text:
                slot_label.config(text=slot_text)
            count_text = f"{len(vids)} en espera"
            if count_label.cget("text") != count_text:
                count_label.config(text=count_text)

            old_order = list(rendered_order)
            old_head = old_order[0] if old_order else None
            old_ids = set(old_order)
            new_ids = set(vids)
            for vehicle_id in old_ids - new_ids:
                chips.pop(vehicle_id).destroy()

            desired_separators = set(vids[:-1])
            for vehicle_id in set(separators) - desired_separators:
                separators.pop(vehicle_id).destroy()

            added = [vehicle_id for vehicle_id in vids if vehicle_id not in old_ids]
            for vehicle_id in added:
                plate = self._plates.get(vehicle_id, f"Auto #{vehicle_id}")
                chip_width = max(
                    self._chip_base_width,
                    math.ceil(self._chip_font.measure(plate) / font_unit),
                )
                chip = tk.Label(
                    plates_container,
                    text=plate,
                    font=self._chip_font,
                    width=chip_width,
                    padx=8,
                    pady=4,
                    relief="flat",
                    anchor="center",
                    bg=COLOR_BG_PRIMARY,
                    fg=COLOR_TEXT_PRIMARY,
                )
                chips[vehicle_id] = chip

            for vehicle_id in desired_separators - set(separators):
                separators[vehicle_id] = tk.Label(
                    plates_container,
                    text="|",
                    bg=COLOR_BG_CARD,
                    fg=COLOR_TEXT_MUTED,
                    font=(font_family(self), 10),
                )

            for vehicle_id in vids:
                chip = chips.get(vehicle_id)
                plate = self._plates.get(vehicle_id, f"Auto #{vehicle_id}")
                if chip.cget("text") != plate:
                    chip_width = max(
                        self._chip_base_width,
                        math.ceil(self._chip_font.measure(plate) / font_unit),
                    )
                    chip.config(text=plate, width=chip_width)

            new_head = vids[0] if vids else None
            if old_head != new_head:
                for vehicle_id in {old_head, new_head} - {None}:
                    chip = chips.get(vehicle_id)
                    if chip is not None:
                        is_head = vehicle_id == new_head
                        chip.config(
                            bg=COLOR_WAITING_BG if is_head else COLOR_BG_PRIMARY,
                            fg=COLOR_WAITING if is_head else COLOR_TEXT_PRIMARY,
                        )

            retained = [vehicle_id for vehicle_id in old_order if vehicle_id in new_ids]
            if vids != retained + added:
                # A non-append reorder is unusual, but only this changed group is reordered.
                for widget in (*chips.values(), *separators.values()):
                    widget.pack_forget()
                for index, vehicle_id in enumerate(vids):
                    chips[vehicle_id].pack(side="left", padx=(0, 2))
                    if index < len(vids) - 1:
                        separators[vehicle_id].pack(side="left", padx=4)
            else:
                for index, vehicle_id in enumerate(vids):
                    if vehicle_id not in added:
                        continue
                    if index:
                        separators[vids[index - 1]].pack(side="left", padx=4)
                    chips[vehicle_id].pack(side="left", padx=(0, 2))

            rendered_order[:] = vids
            if (group_row.winfo_manager() != "grid"
                    or group_row.grid_info().get("row") != row_index):
                group_row.grid(row=row_index, column=0, sticky="ew", pady=5)

        self._on_items_configure()


__all__ = ["WaitingQueueWidget"]
