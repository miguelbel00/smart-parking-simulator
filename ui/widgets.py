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

from pathlib import Path
import tkinter as tk
from typing import Callable, Iterable

from ui.fonts import font_family
from ui.projection import project_occupied_spaces


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
    """Visual lane representing requests waiting for an eligible space.

    In OS terms, this visualizes requests in the WAITING / BLOCKED state. A
    request may wait for capacity or for its authorized space to become free.
    Uses a horizontally scrollable Canvas so many waiting vehicles never clip.
    """

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=14,
            pady=10,
            **kwargs,
        )
        self._vehicles: list[int] = []
        self._plates: dict[int, str] = {}
        self._img_car = _load_png_icon(self, CAR_OCCUPIED_ICON_PATH, subsample=4)

        # Top Bar Header
        top_bar = tk.Frame(self, bg=COLOR_BG_CARD)
        top_bar.pack(fill="x")

        lbl_title = tk.Label(
            top_bar,
            text="COLA DE ESPERA (solicitudes por recurso disponible)",
            bg=COLOR_BG_CARD,
            fg=COLOR_WAITING,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        )
        lbl_title.pack(side="left")

        self._lbl_count = tk.Label(
            top_bar,
            text="0 vehículos",
            bg=COLOR_WAITING_BG,
            fg=COLOR_WAITING,
            font=(font_family(self), 8, "bold"),
            padx=6,
            pady=1,
        )
        self._lbl_count.pack(side="right")

        # Horizontally scrollable viewport for waiting badges
        viewport = tk.Frame(self, bg=COLOR_BG_CARD)
        viewport.pack(fill="x", pady=(8, 0))

        self._canvas = tk.Canvas(
            viewport,
            bg=COLOR_BG_CARD,
            height=38,
            highlightthickness=0,
            bd=0,
        )
        self._scrollbar = tk.Scrollbar(
            viewport,
            orient="horizontal",
            command=self._canvas.xview,
        )
        self._canvas.configure(xscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="top", fill="x", expand=True)

        # Inner container for vehicle items inside the canvas
        self._items_container = tk.Frame(self._canvas, bg=COLOR_BG_CARD)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._items_container, anchor="nw"
        )
        self._items_container.bind("<Configure>", self._on_items_configure)

        self._lbl_empty = tk.Label(
            self._items_container,
            text="No hay solicitudes en espera.",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 9, "italic"),
        )
        self._lbl_empty.pack(anchor="w", pady=4)

    def _on_items_configure(self, _event: tk.Event | None = None) -> None:
        """Update canvas scrollregion and toggle scrollbar visibility."""
        bbox = self._canvas.bbox("all")
        if bbox is not None:
            self._canvas.configure(scrollregion=bbox)
            content_width = bbox[2] - bbox[0]
            canvas_width = max(self._canvas.winfo_width(), 1)
            if content_width > canvas_width and len(self._vehicles) > 1:
                if not self._scrollbar.winfo_ismapped():
                    self._scrollbar.pack(side="bottom", fill="x", pady=(4, 0))
            elif self._scrollbar.winfo_ismapped():
                self._scrollbar.pack_forget()

    def add_vehicle(self, vehicle_id: int, plate: str | None = None) -> None:
        """Add request identity and plate to the waiting lane."""
        if vehicle_id not in self._vehicles:
            self._vehicles.append(vehicle_id)
            self._plates[vehicle_id] = plate or f"Auto #{vehicle_id}"
            self._refresh()
        elif plate:
            self._plates[vehicle_id] = plate
            self._refresh()

    def remove_vehicle(self, vehicle_id: int) -> None:
        """Remove request identity once it leaves the waiting state."""
        if vehicle_id in self._vehicles:
            self._vehicles.remove(vehicle_id)
            self._plates.pop(vehicle_id, None)
            self._refresh()

    def clear(self) -> None:
        """Clear the waiting lane."""
        self._vehicles.clear()
        self._plates.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Re-render the waiting lane badges."""
        count = len(self._vehicles)
        self._lbl_count.config(text=f"{count} vehículo{'s' if count != 1 else ''}")

        for child in self._items_container.winfo_children():
            child.destroy()

        if not self._vehicles:
            self._lbl_empty = tk.Label(
                self._items_container,
                text="No hay solicitudes en espera.",
                bg=COLOR_BG_CARD,
                fg=COLOR_TEXT_MUTED,
                font=(font_family(self), 9, "italic"),
            )
            self._lbl_empty.pack(anchor="w", pady=4)
            self._canvas.xview_moveto(0.0)
            self._on_items_configure()
            return

        # Render each waiting vehicle horizontally with car icon or ASCII marker
        for idx, vid in enumerate(self._vehicles):
            item = tk.Frame(
                self._items_container,
                bg=COLOR_WAITING_BG,
                highlightbackground=COLOR_WAITING,
                highlightthickness=1,
                padx=8,
                pady=4,
            )
            item.pack(side="left", padx=(0, 6))

            badge_label = f"{self._plates.get(vid, f'Auto #{vid}')} (#{vid})"
            if self._img_car is not None:
                tk.Label(
                    item,
                    image=self._img_car,
                    text=f" {badge_label}",
                    compound="left",
                    bg=COLOR_WAITING_BG,
                    fg=COLOR_TEXT_PRIMARY,
                    font=(font_family(self), 9, "bold"),
                ).pack(side="left")
            else:
                tk.Label(
                    item,
                    text=f"AUTO {badge_label}",
                    bg=COLOR_WAITING_BG,
                    fg=COLOR_TEXT_PRIMARY,
                    font=(font_family(self), 9, "bold"),
                ).pack(side="left")

            if idx < len(self._vehicles) - 1:
                tk.Label(
                    self._items_container,
                    text="<-",
                    bg=COLOR_BG_CARD,
                    fg=COLOR_WAITING,
                    font=(font_family(self), 10, "bold"),
                ).pack(side="left", padx=(0, 6))

        self._items_container.update_idletasks()
        self._on_items_configure()


class EventLogWidget(tk.Frame):
    """Terminal-like scrollable log displaying real-time concurrency events.

    In OS terms, this widget displays the event stream consumed from
    the thread-safe queue.Queue (Producer-Consumer pattern).
    Caps stored lines to `max_lines` so the log never grows without bound.
    """

    DEFAULT_MAX_LINES = 500

    def __init__(self, parent: tk.Widget, max_lines: int = DEFAULT_MAX_LINES, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=10,
            **kwargs,
        )
        if max_lines < 1:
            raise ValueError("max_lines must be positive")
        self.max_lines = max_lines
        self.line_count = 0

        # Header with title and clear button
        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 6))

        tk.Label(
            header,
            text="REGISTRO DE EVENTOS (queue.Queue)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=(font_family(self), 9, "bold"),
        ).pack(side="left")

        btn_clear = tk.Button(
            header,
            text="Limpiar",
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
        btn_clear.pack(side="right")

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

    def log(self, event_type: str, message: str, timestamp_str: str) -> None:
        """Append an event line with specialized color tagging and enforce max_lines."""
        self._text.config(state="normal")

        type_tag = self.TAG_MAP.get(event_type, "MSG")

        self._text.insert("end", f"[{timestamp_str}] ", "TIME")
        self._text.insert("end", f"[{event_type}] ", type_tag)
        self._text.insert("end", f"{message}\n", "MSG")
        self.line_count += 1

        if self.line_count > self.max_lines:
            excess = self.line_count - self.max_lines
            self._text.delete("1.0", f"{excess + 1}.0")
            self.line_count = self.max_lines

        self._text.see("end")
        self._text.config(state="disabled")

    def clear(self) -> None:
        """Clear all lines from the log."""
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self.line_count = 0
        self._text.config(state="disabled")


class MetricsSummaryWidget(tk.Frame):
    """Secondary dashboard panel displaying extended simulation & OS metrics.

    Surfaces metrics computed by `SimulationMetrics.snapshot()` that are not
    part of the 7 primary request-counter cards:
    - Average waiting time (`average_waiting_time`)
    - Average parking duration (`average_parking_time`)
    - Peak waiting queue length (`peak_waiting`)
    - Peak slot occupancy (`peak_occupancy`)
    - Total simulation duration (`total_duration`)
    Also provides an on-demand / end-of-run summary dialog with the full report.
    """

    def __init__(self, parent: tk.Widget, capacity: int = 5, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=14,
            pady=8,
            **kwargs,
        )
        self.capacity = capacity
        self._last_report: str = ""
        self._summary_window: tk.Toplevel | None = None

        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 6))

        tk.Label(
            header,
            text="TELEMETRÍA DE DESEMPEÑO Y ESTADÍSTICAS DE EJECUCIÓN",
            bg=COLOR_BG_CARD,
            fg=COLOR_INFO,
            font=(font_family(self), 9, "bold"),
            anchor="w",
        ).pack(side="left")

        self._btn_report = tk.Button(
            header,
            text="Ver Resumen Final",
            bg=COLOR_INFO_BG,
            fg=COLOR_INFO,
            activebackground=COLOR_INFO,
            activeforeground=COLOR_BG_PRIMARY,
            font=(font_family(self), 8, "bold"),
            relief="flat",
            padx=10,
            pady=2,
            cursor="hand2",
            state="disabled",
            command=self.show_report_dialog,
        )
        self._btn_report.pack(side="right")

        self._lbl_banner = tk.Label(
            header,
            text="Sin resumen final aún",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8, "italic"),
            padx=8,
        )
        self._lbl_banner.pack(side="right")

        metrics_row = tk.Frame(self, bg=COLOR_BG_CARD)
        metrics_row.pack(fill="x")

        self._items: dict[str, tk.Label] = {}
        definitions = (
            ("avg_wait", "Espera Promedio", "0.00s", COLOR_WAITING),
            ("avg_parking", "Estacionamiento Prom.", "0.00s", COLOR_AVAILABLE),
            ("peak_waiting", "Pico en Espera", "0", COLOR_WAITING),
            ("peak_occupancy", "Pico de Ocupación", f"0 / {capacity}", COLOR_OCCUPIED),
            ("duration", "Duración Total", "N/D", COLOR_INFO),
        )
        for col_idx, (key, label_text, initial, color) in enumerate(definitions):
            cell = tk.Frame(metrics_row, bg=COLOR_BG_PRIMARY, padx=10, pady=6)
            cell.grid(
                row=0,
                column=col_idx,
                sticky="nsew",
                padx=(0, 6 if col_idx < len(definitions) - 1 else 0),
            )
            metrics_row.grid_columnconfigure(col_idx, weight=1, uniform="telemetry_col")

            tk.Label(
                cell,
                text=label_text.upper(),
                bg=COLOR_BG_PRIMARY,
                fg=COLOR_TEXT_MUTED,
                font=(font_family(self), 8, "bold"),
                anchor="w",
            ).pack(fill="x")

            val_lbl = tk.Label(
                cell,
                text=initial,
                bg=COLOR_BG_PRIMARY,
                fg=color,
                font=(font_family(self), 12, "bold"),
                anchor="w",
            )
            val_lbl.pack(fill="x", pady=(2, 0))
            self._items[key] = val_lbl

    def update_from_snapshot(
        self,
        snapshot: dict[str, float | int | None],
        report_text: str | None = None,
    ) -> None:
        """Refresh telemetry labels from a `SimulationMetrics.snapshot()` dict."""
        avg_wait = float(snapshot.get("average_waiting_time") or 0.0)
        avg_park = float(snapshot.get("average_parking_time") or 0.0)
        peak_wait = int(snapshot.get("peak_waiting") or 0)
        peak_occ = int(snapshot.get("peak_occupancy") or 0)
        duration = snapshot.get("total_duration")

        self._items["avg_wait"].config(text=f"{avg_wait:.2f}s")
        self._items["avg_parking"].config(text=f"{avg_park:.2f}s")
        self._items["peak_waiting"].config(text=str(peak_wait))
        self._items["peak_occupancy"].config(text=f"{peak_occ} / {self.capacity}")
        self._items["duration"].config(
            text=f"{float(duration):.2f}s" if duration is not None else "En curso"
            if snapshot.get("total_generated", 0)
            else "N/D"
        )

        if report_text:
            self._last_report = report_text
            self._btn_report.config(state="normal")
        if duration is not None:
            self._lbl_banner.config(
                text=f"Simulación completada en {float(duration):.2f}s",
                fg=COLOR_AVAILABLE,
            )
            self._btn_report.config(state="normal")

    def reset(self) -> None:
        """Reset displayed telemetry values at the start of a new simulation run."""
        self._items["avg_wait"].config(text="0.00s")
        self._items["avg_parking"].config(text="0.00s")
        self._items["peak_waiting"].config(text="0")
        self._items["peak_occupancy"].config(text=f"0 / {self.capacity}")
        self._items["duration"].config(text="En curso")
        self._lbl_banner.config(text="Ejecución en progreso...", fg=COLOR_INFO)

    def show_report_dialog(self) -> None:
        """Open or focus a Toplevel window showing the full final metrics report."""
        if not self._last_report:
            return
        if self._summary_window is not None and self._summary_window.winfo_exists():
            self._summary_window.lift()
            return

        win = tk.Toplevel(self)
        win.title("Resumen Final de la Simulación")
        win.geometry("480x340")
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
        txt.insert("1.0", self._last_report)
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
    """Header and controls toolbar for starting/stopping the simulator."""

    MAX_STATUS_CHARS = 36

    def __init__(
        self,
        parent: tk.Widget,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=COLOR_BG_CARD, padx=16, pady=12, **kwargs)
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
            text="Monitor de Concurrencia y Sincronización (SO)",
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
        """Update visual controls when simulation finishes or stops."""
        self.status_message = "FINALIZADA"
        self._lbl_status.config(
            text="FINALIZADA",
            bg=COLOR_BORDER,
            fg=COLOR_INFO,
        )
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")

    def set_pending(self, message: str) -> None:
        """Keep both run controls unavailable during a lifecycle transition."""
        self.status_message = str(message)
        is_error = str(message).upper().startswith("ERROR")
        self._lbl_status.config(
            text=self._format_status_text(message),
            bg=COLOR_OCCUPIED_BG if is_error else COLOR_BORDER,
            fg=COLOR_OCCUPIED if is_error else COLOR_INFO,
        )
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="disabled")
