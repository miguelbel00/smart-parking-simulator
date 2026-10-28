"""Grouped pending requests visualizer organized by authorized parking slot."""

from __future__ import annotations

import tkinter as tk

from ui.components.theme import (
    CAR_OCCUPIED_ICON_PATH,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_INFO_BG,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    COLOR_WAITING_BG,
    _load_png_icon,
    font_family,
)
from ui.projection import ParkingProjection


class WaitingQueueWidget(tk.Frame):
    """Visual panel grouping pending requests by their authorized parking slot.

    Reflects the project's actual scheduling policy: FIFO among eligible
    requests and strict FIFO per authorized slot. Includes accepted requests
    from `VEHICLE_CREATED` as well as `VEHICLE_WAITING`, in observed acceptance
    order, without deciding admission or replacing Core logic.
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
        self._img_car = _load_png_icon(self, CAR_OCCUPIED_ICON_PATH, subsample=4)

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
        self._lbl_empty.pack(anchor="w", pady=4)

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
        """Synchronize pending groups directly from the canonical projection."""
        self._vehicles = list(projection.pending_order)
        self._plates.clear()
        self._authorized_slots.clear()
        self._states.clear()
        for vid in self._vehicles:
            rec = projection.requests.get(vid)
            if rec is not None:
                self._plates[vid] = rec.plate or f"Auto #{vid}"
                self._authorized_slots[vid] = rec.authorized_slot
                self._states[vid] = rec.state
            else:
                self._plates[vid] = f"Auto #{vid}"
                self._authorized_slots[vid] = None
                self._states[vid] = "WAITING"
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
        """Re-render pending requests grouped by their authorized parking slot."""
        count = len(self._vehicles)
        self._lbl_count.config(
            text=f"{count} pendiente{'s' if count != 1 else ''}"
        )

        for child in self._items_container.winfo_children():
            child.destroy()

        if not self._vehicles:
            self._lbl_empty = tk.Label(
                self._items_container,
                text="No hay solicitudes pendientes de ingreso.",
                bg=COLOR_BG_CARD,
                fg=COLOR_TEXT_MUTED,
                font=(font_family(self), 9, "italic"),
            )
            self._lbl_empty.pack(anchor="w", pady=4)
            self._canvas.xview_moveto(0.0)
            self._canvas.yview_moveto(0.0)
            self._on_items_configure()
            return

        groups = self.grouped_pending()
        # Sort group rows by slot number (1..N, then None) while keeping acceptance order inside each group
        sorted_slots = sorted(
            groups.keys(), key=lambda s: (s is None, s if s is not None else 0)
        )

        for slot_key in sorted_slots:
            vids = groups[slot_key]
            group_row = tk.Frame(self._items_container, bg=COLOR_BG_CARD)
            group_row.pack(fill="x", anchor="w", pady=2)

            slot_label = (
                f"Puesto #{slot_key}:" if slot_key is not None else "Puesto s/a:"
            )
            tk.Label(
                group_row,
                text=slot_label,
                width=11,
                anchor="w",
                bg=COLOR_BG_PRIMARY,
                fg=COLOR_INFO,
                font=(font_family(self), 8, "bold"),
                padx=6,
                pady=3,
            ).pack(side="left", padx=(0, 6))

            for idx, vid in enumerate(vids):
                plate_str = self._plates.get(vid, f"Auto #{vid}")
                slot_tag = f"Puesto #{slot_key}" if slot_key is not None else "—"
                state_str = self._states.get(vid, "WAITING")
                badge_bg = COLOR_WAITING_BG if state_str == "WAITING" else COLOR_INFO_BG
                badge_border = COLOR_WAITING if state_str == "WAITING" else COLOR_INFO

                item = tk.Frame(
                    group_row,
                    bg=badge_bg,
                    highlightbackground=badge_border,
                    highlightthickness=1,
                    padx=6,
                    pady=2,
                )
                item.pack(side="left", padx=(0, 4))

                badge_text = f"{plate_str} (#{vid} · {slot_tag})"
                if self._img_car is not None:
                    tk.Label(
                        item,
                        image=self._img_car,
                        text=f" {badge_text}",
                        compound="left",
                        bg=badge_bg,
                        fg=COLOR_TEXT_PRIMARY,
                        font=(font_family(self), 8, "bold"),
                    ).pack(side="left")
                else:
                    tk.Label(
                        item,
                        text=badge_text,
                        bg=badge_bg,
                        fg=COLOR_TEXT_PRIMARY,
                        font=(font_family(self), 8, "bold"),
                    ).pack(side="left")

                if idx < len(vids) - 1:
                    tk.Label(
                        group_row,
                        text="→",
                        bg=COLOR_BG_CARD,
                        fg=COLOR_WAITING,
                        font=(font_family(self), 9, "bold"),
                    ).pack(side="left", padx=(0, 4))

        self._items_container.update_idletasks()
        self._on_items_configure()


__all__ = ["WaitingQueueWidget"]
