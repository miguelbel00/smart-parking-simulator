"""Reusable UI widgets for the smart parking simulator.

This module provides graphical components built with Tkinter for:
- Stat cards (KPI metrics representing Semaphore capacity and counters)
- Individual parking slots (discrete shared resources)
- Parking lot slot grid
- Waiting queue visualizer (threads blocked waiting for resources)
- Concurrency event log terminal (displays events consumed from queue.Queue)
- Simulation control bar
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable


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
WAITING_PREVIEW_LIMIT = 5


def waiting_queue_preview(vehicle_ids: Iterable[int], limit: int = WAITING_PREVIEW_LIMIT) -> str:
    """Format a readable bounded preview without changing the source queue."""
    ids = tuple(vehicle_ids)
    visible_ids = ids[:limit]
    preview = "  ·  ".join(f"#{vehicle_id}" for vehicle_id in visible_ids)
    overflow = len(ids) - len(visible_ids)
    if overflow:
        preview += f"  ·  +{overflow} más"
    return preview


class StatCard(tk.Frame):
    """Card widget displaying a KPI metric (title, value, and subtitle).

    In OS terms, these cards display the state of shared counters,
    such as total semaphore capacity, acquired permits, and blocked threads.
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        initial_value: str = "0",
        subtitle: str = "",
        value_color: str = COLOR_TEXT_PRIMARY,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=16,
            pady=12,
            **kwargs,
        )
        self.value_color = value_color

        # Card Title
        self._lbl_title = tk.Label(
            self,
            text=title.upper(),
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self._lbl_title.pack(fill="x")

        # Large Metric Value
        self._lbl_value = tk.Label(
            self,
            text=initial_value,
            bg=COLOR_BG_CARD,
            fg=self.value_color,
            font=("Segoe UI", 22, "bold"),
            anchor="w",
        )
        self._lbl_value.pack(fill="x", pady=(2, 0))

        # Optional descriptive subtitle
        self._lbl_subtitle = tk.Label(
            self,
            text=subtitle,
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        if subtitle:
            self._lbl_subtitle.pack(fill="x")

    def update_value(self, value: str | int, subtitle: str | None = None) -> None:
        """Update the displayed value and optional subtitle."""
        self._lbl_value.config(text=str(value))
        if subtitle is not None:
            self._lbl_subtitle.config(text=subtitle)


class ParkingSlotWidget(tk.Frame):
    """Graphical representation of a single parking bay / space.

    In OS terms, each slot represents a discrete shared resource unit
    with mutual exclusion: at most one vehicle thread can hold it at any time.
    """

    def __init__(self, parent: tk.Widget, space_id: int, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=10,
            pady=10,
            **kwargs,
        )
        self.space_id = space_id
        self.occupied_by: int | None = None

        # Space Identifier (e.g., Espacio #1)
        self._lbl_id = tk.Label(
            self,
            text=f"Espacio #{space_id}",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 9, "bold"),
        )
        self._lbl_id.pack(anchor="center")

        # Visual Icon (🅿️ when available, 🚗 when occupied)
        self._lbl_icon = tk.Label(
            self,
            text="🅿️",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=("Segoe UI", 24),
        )
        self._lbl_icon.pack(anchor="center", pady=(4, 2))

        # Status Badge (DISPONIBLE / OCUPADO)
        self._lbl_status = tk.Label(
            self,
            text="DISPONIBLE",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=2,
        )
        self._lbl_status.pack(anchor="center", pady=(4, 0))

        # Vehicle Details
        self._lbl_detail = tk.Label(
            self,
            text="Libre",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 8),
        )
        self._lbl_detail.pack(anchor="center", pady=(2, 0))

    def set_occupied(self, vehicle_id: int) -> None:
        """Mark slot as occupied by a vehicle thread."""
        self.occupied_by = vehicle_id
        self.config(highlightbackground=COLOR_OCCUPIED, highlightthickness=2)
        self._lbl_icon.config(text="🚗")
        self._lbl_status.config(
            text="OCUPADO",
            bg=COLOR_OCCUPIED_BG,
            fg=COLOR_OCCUPIED,
        )
        self._lbl_detail.config(
            text=f"Auto #{vehicle_id}",
            fg=COLOR_TEXT_PRIMARY,
        )

    def set_available(self) -> None:
        """Mark slot as free when the vehicle thread leaves."""
        self.occupied_by = None
        self.config(highlightbackground=COLOR_BORDER, highlightthickness=1)
        self._lbl_icon.config(text="🅿️")
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
    """Compact two-bank schematic of parking spaces with a central aisle."""

    SLOT_WIDTH = 54
    ROW_HEIGHT = 34
    BANK_GAP = 30
    PADDING = 8

    def __init__(self, parent: tk.Widget, columns: int = 5, **kwargs) -> None:
        super().__init__(parent, bg=COLOR_BG_PRIMARY, **kwargs)
        self.columns = columns
        self.slots: dict[int, dict[str, int]] = {}
        self.canvas = tk.Canvas(
            self, bg=COLOR_BG_PRIMARY, highlightthickness=0,
            yscrollincrement=self.ROW_HEIGHT,
        )
        scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

    @classmethod
    def slot_bounds(cls, space_id: int, columns: int = 5) -> tuple[int, int, int, int]:
        """Return the rectangle for a one-based space in the two-bank layout."""
        zero_based = space_id - 1
        row, position = divmod(zero_based, columns * 2)
        bank_column = position % columns
        in_right_bank = position >= columns
        x = cls.PADDING + bank_column * cls.SLOT_WIDTH
        if in_right_bank:
            x += columns * cls.SLOT_WIDTH + cls.BANK_GAP
        y = cls.PADDING + row * cls.ROW_HEIGHT
        return x, y, x + cls.SLOT_WIDTH - 4, y + cls.ROW_HEIGHT - 4

    def setup_slots(self, capacity: int) -> None:
        """Instantiate slot widgets based on configured parking capacity."""
        self.canvas.delete("all")
        self.slots.clear()

        for index in range(1, capacity + 1):
            bounds = self.slot_bounds(index, self.columns)
            rect = self.canvas.create_rectangle(
                *bounds, fill=COLOR_AVAILABLE_BG, outline=COLOR_AVAILABLE, width=1,
            )
            label = self.canvas.create_text(
                bounds[0] + 4, bounds[1] + 5,
                text=f"#{index}", fill=COLOR_AVAILABLE,
                anchor="nw", font=("Segoe UI", 8, "bold"),
            )
            detail = self.canvas.create_text(
                bounds[0] + 4, bounds[1] + 20,
                text="LIBRE", fill=COLOR_AVAILABLE, anchor="nw",
                font=("Segoe UI", 8),
            )
            self.slots[index] = {"rect": rect, "label": label, "detail": detail}

        rows = (capacity + self.columns * 2 - 1) // (self.columns * 2)
        width = self.PADDING * 2 + self.columns * self.SLOT_WIDTH * 2 + self.BANK_GAP
        height = self.PADDING * 2 + rows * self.ROW_HEIGHT
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def occupy_slot(self, space_id: int, vehicle_id: int) -> None:
        """Mark a specific slot as occupied."""
        if space_id in self.slots:
            slot = self.slots[space_id]
            self.canvas.itemconfigure(slot["rect"], fill=COLOR_OCCUPIED_BG, outline=COLOR_OCCUPIED)
            self.canvas.itemconfigure(slot["label"], fill=COLOR_OCCUPIED)
            self.canvas.itemconfigure(slot["detail"], text=f"Auto #{vehicle_id}", fill=COLOR_OCCUPIED)

    def free_slot(self, space_id: int) -> None:
        """Mark a specific slot as free."""
        if space_id in self.slots:
            slot = self.slots[space_id]
            self.canvas.itemconfigure(slot["rect"], fill=COLOR_AVAILABLE_BG, outline=COLOR_AVAILABLE)
            self.canvas.itemconfigure(slot["label"], fill=COLOR_AVAILABLE)
            self.canvas.itemconfigure(slot["detail"], text="LIBRE", fill=COLOR_AVAILABLE)

    def sync_from_snapshot(self, occupied_spaces: Iterable[tuple[int, int]]) -> None:
        """Synchronize visible slots from Core's zero-based snapshot IDs."""
        occupied_dict = {space_id + 1: vehicle_id for space_id, vehicle_id in occupied_spaces}
        for space_id, slot in self.slots.items():
            if space_id in occupied_dict:
                self.occupy_slot(space_id, occupied_dict[space_id])
            else:
                self.free_slot(space_id)

    def reset(self) -> None:
        """Reset all slots to available."""
        for space_id in self.slots:
            self.free_slot(space_id)


class WaitingQueueWidget(tk.Frame):
    """Visual lane representing queued threads waiting for a free space.

    In OS terms, this visualizes the threads currently in the WAITING / BLOCKED
    state because the Semaphore has 0 available permits.
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

        # Top Bar Header
        top_bar = tk.Frame(self, bg=COLOR_BG_CARD)
        top_bar.pack(fill="x")

        lbl_title = tk.Label(
            top_bar,
            text="COLA DE ESPERA (Hilos bloqueados esperando Semaphore)",
            bg=COLOR_BG_CARD,
            fg=COLOR_WAITING,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        lbl_title.pack(side="left")

        self._lbl_count = tk.Label(
            top_bar,
            text="0 vehículos",
            bg=COLOR_WAITING_BG,
            fg=COLOR_WAITING,
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=1,
        )
        self._lbl_count.pack(side="right")

        # Container for vehicle items in the waiting lane
        self._items_container = tk.Frame(self, bg=COLOR_BG_CARD)
        self._items_container.pack(fill="x", pady=(8, 0))

        self._lbl_empty = tk.Label(
            self._items_container,
            text="No hay vehículos en espera. Todos los hilos tienen recurso asignado.",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 9, "italic"),
        )
        self._lbl_empty.pack(anchor="w", pady=4)

    def add_vehicle(self, vehicle_id: int) -> None:
        """Add vehicle thread ID to waiting lane."""
        if vehicle_id not in self._vehicles:
            self._vehicles.append(vehicle_id)
            self._refresh()

    def remove_vehicle(self, vehicle_id: int) -> None:
        """Remove vehicle thread ID once admitted to a slot."""
        if vehicle_id in self._vehicles:
            self._vehicles.remove(vehicle_id)
            self._refresh()

    def clear(self) -> None:
        """Clear the waiting lane."""
        self._vehicles.clear()
        self._refresh()

    def _refresh(self) -> None:
        """Render a bounded preview while retaining every queued vehicle ID."""
        count = len(self._vehicles)
        self._lbl_count.config(text=f"{count} vehículo{'s' if count != 1 else ''}")

        for child in self._items_container.winfo_children():
            child.destroy()

        if not self._vehicles:
            self._lbl_empty = tk.Label(
                self._items_container,
                text="No hay vehículos en espera. Todos los hilos tienen recurso asignado.",
                bg=COLOR_BG_CARD,
                fg=COLOR_TEXT_MUTED,
                font=("Segoe UI", 9, "italic"),
            )
            self._lbl_empty.pack(anchor="w", pady=4)
            return

        tk.Label(
            self._items_container,
            text=waiting_queue_preview(self._vehicles),
            bg=COLOR_WAITING_BG,
            fg=COLOR_TEXT_PRIMARY,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            padx=8,
            pady=4,
        ).pack(fill="x")


class EventLogWidget(tk.Frame):
    """Terminal-like scrollable log displaying real-time concurrency events.

    In OS terms, this widget displays the event stream consumed from
    the thread-safe queue.Queue (Producer-Consumer pattern).
    """

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(
            parent,
            bg=COLOR_BG_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=10,
            **kwargs,
        )

        # Header with title and clear button
        header = tk.Frame(self, bg=COLOR_BG_CARD)
        header.pack(fill="x", pady=(0, 6))

        tk.Label(
            header,
            text="REGISTRO DE EVENTOS (queue.Queue)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        btn_clear = tk.Button(
            header,
            text="Limpiar",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_PRIMARY,
            activebackground=COLOR_BG_PRIMARY,
            activeforeground=COLOR_TEXT_PRIMARY,
            font=("Segoe UI", 8),
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
            font=("Consolas", 9),
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
        self._text.tag_config("SYSTEM", foreground="#38bdf8", font=("Consolas", 9, "bold"))
        self._text.tag_config("MSG", foreground=COLOR_TEXT_PRIMARY)

    def log(self, event_type: str, message: str, timestamp_str: str) -> None:
        """Append an event line with specialized color tagging."""
        self._text.config(state="normal")

        tag_map = {
            "VEHICLE_CREATED": "CREATED",
            "VEHICLE_WAITING": "WAITING",
            "VEHICLE_ENTERED": "ENTERED",
            "VEHICLE_EXITED": "EXITED",
            "VEHICLE_FINISHED": "FINISHED",
            "SIMULATION_STARTED": "SYSTEM",
            "SIMULATION_FINISHED": "SYSTEM",
        }
        type_tag = tag_map.get(event_type, "MSG")

        self._text.insert("end", f"[{timestamp_str}] ", "TIME")
        self._text.insert("end", f"[{event_type}] ", type_tag)
        self._text.insert("end", f"{message}\n", "MSG")

        self._text.see("end")
        self._text.config(state="disabled")

    def clear(self) -> None:
        """Clear all lines from the log."""
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.config(state="disabled")


class ControlBarWidget(tk.Frame):
    """Header and controls toolbar for starting/stopping the simulator."""

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

        # Application Title & Subtitle
        title_box = tk.Frame(self, bg=COLOR_BG_CARD)
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="Smart Parking Simulator",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_PRIMARY,
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Monitor de Concurrencia y Sincronización (SO)",
            bg=COLOR_BG_CARD,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        # Action Buttons on the right
        btn_box = tk.Frame(self, bg=COLOR_BG_CARD)
        btn_box.pack(side="right")

        # Simulation status badge
        self._lbl_status = tk.Label(
            btn_box,
            text="DETENIDO",
            bg=COLOR_BORDER,
            fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
        )
        self._lbl_status.pack(side="left", padx=(0, 14))

        # Start button
        self._btn_start = tk.Button(
            btn_box,
            text="▶ Iniciar Simulación",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
            activebackground=COLOR_AVAILABLE,
            activeforeground=COLOR_BG_PRIMARY,
            font=("Segoe UI", 9, "bold"),
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
            text="⏹ Detener",
            bg=COLOR_OCCUPIED_BG,
            fg=COLOR_OCCUPIED,
            activebackground=COLOR_OCCUPIED,
            activeforeground=COLOR_BG_PRIMARY,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            state="disabled",
            command=self._handle_stop,
        )
        self._btn_stop.pack(side="left")

    def _handle_start(self) -> None:
        if self.on_start:
            self.on_start()

    def _handle_stop(self) -> None:
        if self.on_stop:
            self.on_stop()

    def set_running(self) -> None:
        """Update visual controls when simulation is active."""
        self._lbl_status.config(
            text="EN EJECUCIÓN",
            bg=COLOR_AVAILABLE_BG,
            fg=COLOR_AVAILABLE,
        )
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")

    def set_stopped(self) -> None:
        """Update visual controls when simulation finishes or stops."""
        self._lbl_status.config(
            text="FINALIZADA",
            bg=COLOR_BORDER,
            fg=COLOR_INFO,
        )
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")
