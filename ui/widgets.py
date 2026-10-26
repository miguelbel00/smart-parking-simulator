"""Reusable UI widgets for the smart parking simulator.

This module provides graphical components built with Tkinter for:
- Stat cards (KPI metrics representing Semaphore capacity and counters)
- Individual parking slots (discrete shared resources)
- Parking lot slot grid
- Waiting queue visualizer (requests waiting for eligible resources)
- Concurrency event log terminal (displays events consumed from queue.Queue)
- Simulation control bar
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable

from ui.fonts import font_family
from ui.projection import ParkingProjection, RequestRecord, project_occupied_spaces


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
PARKING_SPACE_ICON_PATH = ASSETS_DIR / "parking_space_icon.png"
CAR_OCCUPIED_ICON_PATH = ASSETS_DIR / "car_occupied_icon.png"


def _load_png_icon(
    master: tk.Misc, path: Path, subsample: int = 2
) -> tk.PhotoImage | None:
    """Load a PNG asset natively with Tk PhotoImage and downscale by `subsample`."""
    if not path.is_file():
        return None
    try:
        img = tk.PhotoImage(master=master, file=str(path))
        if subsample > 1:
            img = img.subsample(subsample, subsample)
        return img
    except tk.TclError:
        return None


# --- Color Palette (Dark Slate Theme) ---
COLOR_BG_PRIMARY = "#0f172a"      # Slate 900: Main window background
COLOR_BG_CARD = "#1e293b"         # Slate 800: Panel container background
COLOR_BORDER = "#334155"          # Slate 700: Panel borders
COLOR_TEXT_PRIMARY = "#f8fafc"    # Slate 50: Primary readable text
COLOR_TEXT_MUTED = "#94a3b8"      # Slate 400: Subtitles and timestamps

# Semantic State Colors for Operating System Resources
COLOR_AVAILABLE = "#10b981"       # Emerald Green: Resource is free (available permit)
COLOR_AVAILABLE_BG = "#064e3b"    # Dark Emerald background
COLOR_OCCUPIED = "#ef4444"        # Coral Red: Resource acquired (locked space)
COLOR_OCCUPIED_BG = "#7f1d1d"     # Dark Red background
COLOR_WAITING = "#f59e0b"         # Amber: Thread blocked in WAITING state
COLOR_WAITING_BG = "#78350f"      # Dark Amber background
COLOR_INFO = "#38bdf8"            # Sky Blue: Simulation lifecycle events
COLOR_INFO_BG = "#0c4a6e"
COLOR_LOG_BG = "#050811"          # Deep terminal background for event log


class StatCard(tk.Frame):
    """Card widget displaying a KPI metric (title, value, and subtitle).

    In OS terms, these cards display the state of shared counters,
    such as admission counts, current occupancy, and terminal outcomes.
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        initial_value: str = "0",
        subtitle: str = "",
        value_color: str = COLOR_TEXT_PRIMARY,
        compact: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=10 if not compact else 8,
            pady=8 if not compact else 6,
            **kwargs,
        )
        self.value_color = value_color
        self.value: str = str(initial_value)
        self.subtitle: str = subtitle

        # Card Title
        self._lbl_title = tk.Label(
            self,
            text=title.upper(),
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "bold"),
            anchor="w",
        )
        self._lbl_title.pack(fill="x")

        # Large Metric Value
        value_font_size = 14 if compact else 18
        self._lbl_value = tk.Label(
            self,
            text=initial_value,
            bg=COLOR_BG_CARD,
            fg=self.value_color,
            font=(font_family(self), value_font_size, "bold"),
            anchor="w",
        )
        self._lbl_value.pack(fill="x", pady=(2, 0))

        # Optional descriptive subtitle
        self._lbl_subtitle = tk.Label(
            self,
            text=subtitle,
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
            anchor="w",
        )
        if subtitle:
            self._lbl_subtitle.pack(fill="x")

    def update_value(self, value: str | int, subtitle: str | None = None) -> None:
        """Update the displayed value and optional subtitle."""
        self.value = str(value)
        self._lbl_value.config(text=self.value)
        if subtitle is not None:
            self.update_subtitle(subtitle)

    def update_subtitle(self, subtitle: str) -> None:
        """Update and ensure visibility of the descriptive subtitle."""
        self.subtitle = subtitle
        self._lbl_subtitle.config(text=subtitle)
        if subtitle and not self._lbl_subtitle.winfo_ismapped():
            self._lbl_subtitle.pack(fill="x")


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

    def render_occupied(self, occupied: dict[int, int],
                        plates: dict[int, str] | None = None) -> None:
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


class RequestTrackingTableWidget(tk.Frame):
    """Table tracking the full lifecycle of every vehicle request in the run.

    Columns:
    - ID (`id`)
    - Placa (`plate`)
    - Puesto autorizado (`authorized_slot`)
    - Puesto ocupado (`occupied_slot`)
    - Estado / Resultado (`state`)
    - Tiempo de espera (`waiting_time`)
    - Motivo (`reason`)

    Retains finished, cancelled, and rejected rows so the user can inspect
    the full run history without relying solely on raw logs.
    """

    COLUMNS = (
        ("id", "ID", 52, "center"),
        ("plate", "Placa", 88, "center"),
        ("authorized_slot", "Puesto Aut.", 86, "center"),
        ("occupied_slot", "Puesto Ocup.", 88, "center"),
        ("state", "Estado / Resultado", 118, "center"),
        ("waiting_time", "Espera", 74, "e"),
        ("reason", "Motivo", 130, "w"),
    )

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
        self._row_ids: dict[int, str] = {}

        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 6))

        tk.Label(
            header,
            text="SEGUIMIENTO DE SOLICITUDES (ciclo de vida en tiempo real)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        ).pack(side="left")

        self._lbl_summary = tk.Label(
            header,
            text="0 solicitudes registradas",
            bg=COLOR_BG_PRIMARY,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
            padx=6,
            pady=1,
        )
        self._lbl_summary.pack(side="right")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Parking.Treeview",
            background=COLOR_LOG_BG,
            fieldbackground=COLOR_LOG_BG,
            foreground=COLOR_TEXT_PRIMARY,
            rowheight=23,
            borderwidth=0,
            font=(font_family(self), 8),
        )
        style.configure(
            "Parking.Treeview.Heading",
            background=COLOR_BG_PRIMARY,
            foreground=COLOR_TEXT_MUTED,
            relief="flat",
            font=(font_family(self), 8, "bold"),
        )
        style.map(
            "Parking.Treeview",
            background=[("selected", COLOR_INFO_BG)],
            foreground=[("selected", COLOR_TEXT_PRIMARY)],
        )

        table_frame = tk.Frame(self, bg=COLOR_LOG_BG)
        table_frame.pack(fill="both", expand=True)

        col_ids = tuple(col[0] for col in self.COLUMNS)
        self._tree = ttk.Treeview(
            table_frame,
            columns=col_ids,
            show="headings",
            height=6,
            style="Parking.Treeview",
        )
        self._vscroll = tk.Scrollbar(
            table_frame, orient="vertical", command=self._tree.yview
        )
        self._tree.configure(yscrollcommand=self._vscroll.set)

        for col_id, heading, width, anchor in self.COLUMNS:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=48, anchor=anchor, stretch=True)

        self._tree.pack(side="left", fill="both", expand=True)
        self._vscroll.pack(side="right", fill="y")

        # Color tags per lifecycle state
        self._tree.tag_configure("CREATED", foreground="#cbd5e1")
        self._tree.tag_configure("WAITING", foreground=COLOR_WAITING)
        self._tree.tag_configure("ENTERED", foreground=COLOR_AVAILABLE)
        self._tree.tag_configure("EXITED", foreground="#c084fc")
        self._tree.tag_configure("FINISHED", foreground=COLOR_INFO)
        self._tree.tag_configure("CANCELLED", foreground="#fb923c")
        self._tree.tag_configure("REJECTED", foreground=COLOR_OCCUPIED)

    def upsert_record(self, record: RequestRecord) -> None:
        """Insert or update a single request row in the table."""
        values = record.as_table_row()
        tag = record.state if record.state in {
            "CREATED", "WAITING", "ENTERED", "EXITED", "FINISHED", "CANCELLED", "REJECTED"
        } else "CREATED"
        iid = self._row_ids.get(record.vehicle_id)
        if iid is not None and self._tree.exists(iid):
            self._tree.item(iid, values=values, tags=(tag,))
        else:
            iid = f"req-{record.vehicle_id}"
            self._tree.insert("", "end", iid=iid, values=values, tags=(tag,))
            self._row_ids[record.vehicle_id] = iid
            self._tree.see(iid)
        count = len(self._row_ids)
        self._lbl_summary.config(
            text=f"{count} solicitud{'es' if count != 1 else ''} registrada{'s' if count != 1 else ''}"
        )

    def sync_from_projection(self, projection: ParkingProjection) -> None:
        """Synchronize all rows from `projection.requests` in observation order."""
        existing_ids = set(projection.requests.keys())
        if not existing_ids and self._row_ids:
            self.clear()
            return
        for record in projection.requests.values():
            self.upsert_record(record)

    def rows(self) -> list[tuple[str, ...]]:
        """Return currently displayed table rows in order."""
        return [
            tuple(str(val) for val in self._tree.item(iid, "values"))
            for iid in self._tree.get_children("")
        ]

    def clear(self) -> None:
        """Clear all rows from the table at the start of a new run."""
        for iid in self._tree.get_children(""):
            self._tree.delete(iid)
        self._row_ids.clear()
        self._lbl_summary.config(text="0 solicitudes registradas")


class EventLogWidget(tk.Frame):
    """Scrollable event log with non-destructive filters by request ID, plate, and event type.

    Filters affect only the visual view; original entries and simulation metrics
    remain untouched. Clearing the view (`Limpiar vista`) never alters persisted
    audit logs.
    """

    DEFAULT_MAX_LINES = 500
    EVENT_TYPES = (
        "TODOS",
        "VEHICLE_CREATED",
        "VEHICLE_WAITING",
        "VEHICLE_ENTERED",
        "VEHICLE_EXITED",
        "VEHICLE_FINISHED",
        "VEHICLE_REJECTED",
        "VEHICLE_CANCELLED",
        "SIMULATION_STARTED",
        "SIMULATION_FINISHED",
        "ENGINE_ERROR",
        "START_REFUSED",
    )

    def __init__(self, parent: tk.Widget, max_lines: int = DEFAULT_MAX_LINES, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
            **kwargs,
        )
        if max_lines < 1:
            raise ValueError("max_lines must be positive")
        self.max_lines = max_lines
        self.line_count = 0
        self._entries: deque[dict[str, Any]] = deque()

        # Header with title, audit note, and "Limpiar vista" button
        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 4))

        title_col = tk.Frame(header, bg=COLOR_BG_CARD)
        title_col.pack(side="left", fill="x", expand=True)

        tk.Label(
            title_col,
            text="REGISTRO CRONOLÓGICO DE EVENTOS",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        ).pack(anchor="w")

        self._lbl_audit_note = tk.Label(
            title_col,
            text="Solo vista local — limpiar o filtrar no modifica la auditoría persistida",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 7),
            anchor="w",
        )
        self._lbl_audit_note.pack(anchor="w")

        self._btn_clear = tk.Button(
            header,
            text="Limpiar vista",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_PRIMARY,
            activebackground=COLOR_BG_PRIMARY,
            activeforeground=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 8),
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.clear,
        )
        self._btn_clear.pack(side="right")

        # Filter Controls Bar (by request ID, plate, and event type)
        filter_bar = tk.Frame(self, bg=COLOR_BG_PRIMARY, padx=6, pady=4)
        filter_bar.pack(fill="x", pady=(0, 6))

        tk.Label(
            filter_bar,
            text="ID:",
            bg=COLOR_BG_PRIMARY,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "bold"),
        ).pack(side="left")

        self.filter_id_var = tk.StringVar(master=self, value="")
        self._entry_id = tk.Entry(
            filter_bar,
            textvariable=self.filter_id_var,
            width=5,
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            relief="flat",
            font=(font_family(self), 8),
        )
        self._entry_id.pack(side="left", padx=(2, 8))

        tk.Label(
            filter_bar,
            text="Placa:",
            bg=COLOR_BG_PRIMARY,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "bold"),
        ).pack(side="left")

        self.filter_plate_var = tk.StringVar(master=self, value="")
        self._entry_plate = tk.Entry(
            filter_bar,
            textvariable=self.filter_plate_var,
            width=9,
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            relief="flat",
            font=(font_family(self), 8),
        )
        self._entry_plate.pack(side="left", padx=(2, 8))

        tk.Label(
            filter_bar,
            text="Tipo:",
            bg=COLOR_BG_PRIMARY,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "bold"),
        ).pack(side="left")

        self.filter_type_var = tk.StringVar(master=self, value="TODOS")
        self._combo_type = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_type_var,
            values=self.EVENT_TYPES,
            state="readonly",
            width=16,
            font=(font_family(self), 8),
        )
        self._combo_type.pack(side="left", padx=(2, 6))

        self._btn_reset_filters = tk.Button(
            filter_bar,
            text="Todos",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 7),
            relief="flat",
            padx=5,
            pady=1,
            cursor="hand2",
            command=self.reset_filters,
        )
        self._btn_reset_filters.pack(side="right")

        self.filter_id_var.trace_add("write", lambda *_: self.apply_filters())
        self.filter_plate_var.trace_add("write", lambda *_: self.apply_filters())
        self.filter_type_var.trace_add("write", lambda *_: self.apply_filters())

        # Scrollable Text container
        text_frame = tk.Frame(self, bg=COLOR_LOG_BG)
        text_frame.pack(fill="both", expand=True)

        self._scrollbar = tk.Scrollbar(text_frame, orient="vertical")
        self._scrollbar.pack(side="right", fill="y")

        self._text = tk.Text(
            text_frame,
            bg=COLOR_LOG_BG,
            fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            font=(font_family(self, fixed=True), 9),
            wrap="word",
            state="disabled",
            yscrollcommand=self._scrollbar.set,
            relief="flat",
            padx=8,
            pady=8,
        )
        self._text.pack(side="left", fill="both", expand=True)
        self._scrollbar.config(command=self._text.yview)

        # Event color tags for visual clarity
        self._text.tag_config("TIME", foreground=COLOR_TEXT_MUTED)
        self._text.tag_config("CREATED", foreground="#cbd5e1")
        self._text.tag_config("WAITING", foreground=COLOR_WAITING)
        self._text.tag_config("ENTERED", foreground=COLOR_AVAILABLE)
        self._text.tag_config("EXITED", foreground="#c084fc")
        self._text.tag_config("FINISHED", foreground=COLOR_INFO)
        self._text.tag_config("REJECTED", foreground=COLOR_OCCUPIED)
        self._text.tag_config("CANCELLED", foreground="#fb923c")
        self._text.tag_config(
            "ERROR", foreground=COLOR_OCCUPIED, font=(font_family(self, fixed=True), 9, "bold")
        )
        self._text.tag_config(
            "SYSTEM", foreground="#38bdf8", font=(font_family(self, fixed=True), 9, "bold")
        )
        self._text.tag_config("MSG", foreground=COLOR_TEXT_PRIMARY)

    # Event type -> color tag; unknown types fall back to plain "MSG".
    TAG_MAP = {
        "VEHICLE_CREATED": "CREATED",
        "VEHICLE_WAITING": "WAITING",
        "VEHICLE_ENTERED": "ENTERED",
        "VEHICLE_EXITED": "EXITED",
        "VEHICLE_FINISHED": "FINISHED",
        "VEHICLE_REJECTED": "REJECTED",
        "VEHICLE_CANCELLED": "CANCELLED",
        "SIMULATION_STARTED": "SYSTEM",
        "SIMULATION_FINISHED": "SYSTEM",
        "ENGINE_ERROR": "ERROR",
        "START_REFUSED": "WAITING",
    }

    def _matches_filter(self, entry: dict[str, Any]) -> bool:
        f_id = self.filter_id_var.get().strip().lstrip("#")
        f_plate = self.filter_plate_var.get().strip().upper()
        f_type = self.filter_type_var.get().strip().upper()

        if f_type and f_type != "TODOS" and entry["event_type"].upper() != f_type:
            return False
        if f_id:
            vid_str = str(entry["vehicle_id"]) if entry["vehicle_id"] is not None else ""
            if vid_str != f_id and f"#{f_id}" not in entry["message"]:
                return False
        if f_plate:
            plate_str = (entry["plate"] or "").upper()
            if f_plate not in plate_str and f_plate not in entry["message"].upper():
                return False
        return True

    def _insert_entry(self, entry: dict[str, Any]) -> None:
        type_tag = self.TAG_MAP.get(entry["event_type"], "MSG")
        self._text.insert("end", f"[{entry['timestamp_str']}] ", "TIME")
        self._text.insert("end", f"[{entry['event_type']}] ", type_tag)
        self._text.insert("end", f"{entry['message']}\n", "MSG")

    def log(
        self,
        event_type: str,
        message: str,
        timestamp_str: str,
        vehicle_id: int | None = None,
        plate: str | None = None,
    ) -> None:
        """Record an event entry, enforce max_lines, and display if matching active filters."""
        if vehicle_id is None:
            match = re.search(r"#(\d+)", message)
            if match:
                vehicle_id = int(match.group(1))
        entry = {
            "event_type": event_type,
            "message": message,
            "timestamp_str": timestamp_str,
            "vehicle_id": vehicle_id,
            "plate": plate,
        }
        self._entries.append(entry)
        while len(self._entries) > self.max_lines:
            self._entries.popleft()

        self.apply_filters()

    def set_filters(
        self,
        *,
        vehicle_id: str | int | None = None,
        plate: str | None = None,
        event_type: str | None = None,
    ) -> None:
        """Programmatically set view filters without altering stored entries."""
        if vehicle_id is not None:
            self.filter_id_var.set(str(vehicle_id))
        if plate is not None:
            self.filter_plate_var.set(plate)
        if event_type is not None:
            self.filter_type_var.set(event_type)
        self.apply_filters()

    def reset_filters(self) -> None:
        """Clear active filters and restore all stored entries to the view."""
        self.filter_id_var.set("")
        self.filter_plate_var.set("")
        self.filter_type_var.set("TODOS")
        self.apply_filters()

    def apply_filters(self) -> None:
        """Re-render visible lines from stored entries according to active filters."""
        while len(self._entries) > self.max_lines:
            self._entries.popleft()

        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        visible = 0
        for entry in self._entries:
            if self._matches_filter(entry):
                self._insert_entry(entry)
                visible += 1
        self.line_count = visible
        self._text.see("end")
        self._text.config(state="disabled")

    def visible_lines(self) -> list[str]:
        """Return currently rendered text lines for inspection."""
        raw = self._text.get("1.0", "end-1c")
        return raw.splitlines() if raw else []

    def clear(self) -> None:
        """Clear the local view without altering persisted audit records or metrics."""
        self._entries.clear()
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self.line_count = 0
        self._text.config(state="disabled")


class MetricsSummaryWidget(tk.Frame):
    """Persistent end-of-run and live execution summary panel.

    Displays consolidated run results directly in the UI without closing the app:
    - Generated, accepted, and rejected requests
    - Finished vehicles and cancelled requests
    - Peak occupancy and average waiting time
    - Explicit warnings if the run or audit was incomplete
    Remains visible after a run finishes until a new run is started.
    """

    def __init__(self, parent: tk.Widget, capacity: int = 5, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
            **kwargs,
        )
        self.capacity = capacity
        self._last_report: str = ""
        self._summary_window: tk.Toplevel | None = None
        self.warning_message: str = ""

        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 4))

        tk.Label(
            header,
            text="RESUMEN DE EJECUCIÓN Y TELEMETRÍA",
            bg=COLOR_BG_CARD,
            fg=COLOR_INFO,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        ).pack(side="left")

        self._btn_report = tk.Button(
            header,
            text="Detalle Completo",
            bg=COLOR_INFO_BG,
            fg=COLOR_INFO,
            activebackground=COLOR_INFO,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 8, "bold"),
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            state="disabled",
            command=self.show_report_dialog,
        )
        self._btn_report.pack(side="right")

        self._lbl_banner = tk.Label(
            header,
            text="Sin ejecución finalizada aún",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "italic"),
            padx=6,
        )
        self._lbl_banner.pack(side="right")

        # Consolidated summary metrics grid (visible directly without opening a dialog)
        metrics_row = tk.Frame(self, bg=COLOR_BG_CARD)
        metrics_row.pack(fill="x")

        self._items: dict[str, tk.Label] = {}
        definitions = (
            ("summary_counts", "Gen / Acep / Rech", "0 / 0 / 0", COLOR_TEXT_PRIMARY),
            ("summary_terminals", "Fin / Cancelados", "0 / 0", COLOR_INFO),
            ("avg_wait", "Espera Promedio", "0.00s", COLOR_WAITING),
            ("avg_parking", "Estac. Promedio", "0.00s", COLOR_AVAILABLE),
            ("peak_waiting", "Pico Espera", "0", COLOR_WAITING),
            ("peak_occupancy", "Máx. Ocupación", f"0 / {capacity}", COLOR_OCCUPIED),
            ("duration", "Duración", "N/D", COLOR_INFO),
        )
        cols_per_row = 4
        for idx, (key, label_text, initial, color) in enumerate(definitions):
            row_idx = idx // cols_per_row
            col_idx = idx % cols_per_row
            cell = tk.Frame(metrics_row, bg=COLOR_BG_PRIMARY, padx=8, pady=4)
            cell.grid(
                row=row_idx,
                column=col_idx,
                sticky="nsew",
                padx=(0, 4 if col_idx < cols_per_row - 1 else 0),
                pady=(0, 4 if row_idx == 0 else 0),
            )
            metrics_row.grid_columnconfigure(col_idx, weight=1, uniform="telemetry_col")

            tk.Label(
                cell,
                text=label_text.upper(),
                bg=COLOR_BG_PRIMARY,
                fg=COLOR_TEXT_MUTED,
                font=(font_family(self), 7, "bold"),
                anchor="w",
            ).pack(fill="x")

            val_lbl = tk.Label(
                cell,
                text=initial,
                bg=COLOR_BG_PRIMARY,
                fg=color,
                font=(font_family(self), 10, "bold"),
                anchor="w",
            )
            val_lbl.pack(fill="x", pady=(1, 0))
            self._items[key] = val_lbl

        # Integrity / Warning status bar at the bottom of the summary
        self._lbl_warning = tk.Label(
            self,
            text="Estado de integridad: sin advertencias.",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
            anchor="w",
            pady=2,
        )
        self._lbl_warning.pack(fill="x", pady=(4, 0))

    def update_from_snapshot(
        self,
        snapshot: dict[str, float | int | None],
        report_text: str | None = None,
        warning: str | None = None,
    ) -> None:
        """Refresh visible summary fields and integrity warnings from `SimulationMetrics.snapshot()`."""
        gen = int(snapshot.get("total_generated") or 0)
        adm = int(snapshot.get("total_admitted") or 0)
        rej = int(snapshot.get("total_rejected") or 0)
        fin = int(snapshot.get("total_finished") or 0)
        can = int(snapshot.get("total_cancelled") or 0)
        avg_wait = float(snapshot.get("average_waiting_time") or 0.0)
        avg_park = float(snapshot.get("average_parking_time") or 0.0)
        peak_wait = int(snapshot.get("peak_waiting") or 0)
        peak_occ = int(snapshot.get("peak_occupancy") or 0)
        duration = snapshot.get("total_duration")

        self._items["summary_counts"].config(text=f"{gen} / {adm} / {rej}")
        self._items["summary_terminals"].config(text=f"{fin} / {can}")
        self._items["avg_wait"].config(text=f"{avg_wait:.2f}s")
        self._items["avg_parking"].config(text=f"{avg_park:.2f}s")
        self._items["peak_waiting"].config(text=str(peak_wait))
        self._items["peak_occupancy"].config(text=f"{peak_occ} / {self.capacity}")
        self._items["duration"].config(
            text=f"{float(duration):.2f}s"
            if duration is not None
            else ("En curso" if gen > 0 else "N/D")
        )

        if report_text:
            self._last_report = report_text
            self._btn_report.config(state="normal")

        if warning:
            self.set_warning(warning)
        elif duration is not None:
            self._lbl_banner.config(
                text=f"Última ejecución: {float(duration):.2f}s",
                fg=COLOR_AVAILABLE,
            )
            self._btn_report.config(state="normal")
            if can > 0:
                self.warning_message = (
                    f"Aviso: Ejecución detenida con {can} solicitud(es) cancelada(s) en espera."
                )
                self._lbl_warning.config(
                    text=self.warning_message,
                    fg=COLOR_WAITING,
                )
            elif not self.warning_message:
                self._lbl_warning.config(
                    text="Ejecución completada y drenada sin advertencias de integridad.",
                    fg=COLOR_AVAILABLE,
                )

    def set_warning(self, warning_text: str) -> None:
        """Display an explicit warning when a run or audit is incomplete."""
        self.warning_message = warning_text
        self._lbl_warning.config(text=warning_text, fg=COLOR_OCCUPIED)
        self._lbl_banner.config(text="Ejecución / auditoría incompleta", fg=COLOR_OCCUPIED)

    def reset(self) -> None:
        """Reset summary values when a new simulation run starts."""
        self.warning_message = ""
        self._items["summary_counts"].config(text="0 / 0 / 0")
        self._items["summary_terminals"].config(text="0 / 0")
        self._items["avg_wait"].config(text="0.00s")
        self._items["avg_parking"].config(text="0.00s")
        self._items["peak_waiting"].config(text="0")
        self._items["peak_occupancy"].config(text=f"0 / {self.capacity}")
        self._items["duration"].config(text="En curso")
        self._lbl_banner.config(text="Ejecución en progreso...", fg=COLOR_INFO)
        self._lbl_warning.config(
            text="Estado de integridad: ejecución en curso.",
            fg=COLOR_TEXT_MUTED,
        )

    def show_report_dialog(self) -> None:
        """Open or focus a Toplevel window showing the full text report."""
        if not self._last_report:
            return
        if self._summary_window is not None and self._summary_window.winfo_exists():
            self._summary_window.lift()
            return

        win = tk.Toplevel(self)
        win.title("Resumen Final de la Simulación")
        win.geometry("480x360")
        win.configure(bg=COLOR_BG_PRIMARY)
        self._summary_window = win

        container = tk.Frame(
            win,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=16,
            pady=14,
        )
        container.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Label(
            container,
            text="ESTADÍSTICAS FINALES DE LA SIMULACIÓN",
            bg=COLOR_BG_CARD,
            fg=COLOR_INFO,
            font=(font_family(self), 10, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        txt = tk.Text(
            container,
            bg=COLOR_LOG_BG,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self, fixed=True), 9),
            relief="flat",
            padx=10,
            pady=10,
            height=13,
            wrap="none",
        )
        report_body = self._last_report
        if self.warning_message:
            report_body = f"{report_body}\n{self.warning_message}\n"
        txt.insert("1.0", report_body)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

        tk.Button(
            container,
            text="Cerrar",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 9, "bold"),
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            command=win.destroy,
        ).pack(anchor="e", pady=(10, 0))


class ControlBarWidget(tk.Frame):
    """Header and controls toolbar for starting/stopping the simulator.

    Clearly distinguishes the 6 lifecycle states:
    - INICIANDO (start command sent)
    - EN EJECUCIÓN (SIMULATION_STARTED confirmed)
    - DETENCIÓN SOLICITADA (user pressed Stop)
    - FINALIZANDO (terminal events / drain in progress)
    - FINALIZADA (run and drain confirmed; ready to start another)
    - ERROR (unrecoverable failure / controlled shutdown)
    """

    MAX_STATUS_CHARS = 36

    def __init__(
        self,
        parent: tk.Widget,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=COLOR_BG_CARD, padx=16, pady=10, **kwargs)
        self.on_start = on_start
        self.on_stop = on_stop
        self.status_message = "DETENIDO"

        # Application Title & Subtitle
        title_box = tk.Frame(self, bg=COLOR_BG_CARD)
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="Smart Parking Simulator",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 14, "bold"),
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Monitor de Concurrencia, Sincronización e IPC (Sistemas Operativos)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9),
        ).pack(anchor="w")

        # Action Buttons on the right
        btn_box = tk.Frame(self, bg=COLOR_BG_CARD)
        btn_box.pack(side="right")

        # Simulation status badge with bounded text length so long errors do not deform layout
        self._lbl_status = tk.Label(
            btn_box,
            text="DETENIDO",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9, "bold"),
            padx=10,
            pady=4,
        )
        self._lbl_status.pack(side="left", padx=(0, 14))

        # Start button
        self._btn_start = tk.Button(
            btn_box,
            text="Iniciar Simulación",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
            activebackground=COLOR_AVAILABLE,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._handle_start,
        )
        self._btn_start.pack(side="left", padx=(0, 8))

        # Stop button
        self._btn_stop = tk.Button(
            btn_box,
            text="Detener",
            bg=COLOR_OCCUPIED_BG,
            fg=COLOR_OCCUPIED,
            activebackground=COLOR_OCCUPIED,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            state="disabled",
            command=self._handle_stop,
        )
        self._btn_stop.pack(side="left")

    @classmethod
    def _format_status_text(cls, message: str) -> str:
        """Truncate overly long status messages so the control bar never deforms."""
        single_line = " ".join(str(message).splitlines()).strip()
        if len(single_line) > cls.MAX_STATUS_CHARS:
            return single_line[: cls.MAX_STATUS_CHARS - 1] + "…"
        return single_line

    def _handle_start(self) -> None:
        if self.on_start:
            self.on_start()

    def _handle_stop(self) -> None:
        if self.on_stop:
            self.on_stop()

    def set_running(self) -> None:
        """Update visual controls when simulation is active."""
        self.status_message = "EN EJECUCIÓN"
        self._lbl_status.config(
            text="EN EJECUCIÓN",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
        )
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")

    def set_stopped(self) -> None:
        """Update visual controls when simulation finishes and drain is confirmed."""
        self.status_message = "FINALIZADA"
        self._lbl_status.config(
            text="FINALIZADA",
            bg=COLOR_INFO_BG,
            fg=COLOR_INFO,
        )
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")

    def set_pending(self, message: str) -> None:
        """Keep both run controls unavailable during a lifecycle transition or error."""
        self.status_message = str(message)
        upper = self.status_message.upper()
        if upper.startswith("ERROR") or upper.startswith("WARNING"):
            bg_color, fg_color = COLOR_OCCUPIED_BG, COLOR_OCCUPIED
        elif "DETENCIÓN" in upper or "STOP" in upper or "CERRANDO" in upper:
            bg_color, fg_color = COLOR_WAITING_BG, COLOR_WAITING
        elif "INICIANDO" in upper or "FINALIZANDO" in upper:
            bg_color, fg_color = COLOR_INFO_BG, COLOR_INFO
        else:
            bg_color, fg_color = COLOR_BORDER, COLOR_INFO

        self._lbl_status.config(
            text=self._format_status_text(message),
            bg=bg_color,
            fg=fg_color,
        )
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="disabled")
