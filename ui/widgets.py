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

from ui.projection import project_occupied_spaces


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

        for index in range(1, capacity + 1):
            row = (index - 1) // self.columns
            col = (index - 1) % self.columns
            slot_widget = ParkingSlotWidget(self, space_id=index)
            slot_widget.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            self.slots[index] = slot_widget

        for col_idx in range(self.columns):
            self.grid_columnconfigure(col_idx, weight=1)

    def occupy_slot(self, slot_key: int, vehicle_id: int) -> None:
        """Mark a projected, 1-based display slot as occupied."""
        self.slots[slot_key].set_occupied(vehicle_id)

    def free_slot(self, slot_key: int) -> None:
        """Free a projected, 1-based display slot."""
        self.slots[slot_key].set_available()

    def sync_from_snapshot(self, occupied_spaces: Iterable[tuple[int, int]]) -> None:
        """Translate raw core snapshot pairs once, then render display slots."""
        self.render_occupied(project_occupied_spaces(occupied_spaces, len(self.slots)))

    def render_occupied(self, occupied: dict[int, int]) -> None:
        """Render already-projected keys, clearing slots absent from the mapping."""
        if any(key not in self.slots for key in occupied):
            raise ValueError("Projected slot is not present in the grid")
        for key, slot in self.slots.items():
            if key in occupied:
                slot.set_occupied(occupied[key])
            else:
                slot.set_available()

    def reset(self) -> None:
        """Reset all slots to available."""
        for slot in self.slots.values():
            slot.reset()


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
        """Re-render the waiting lane badges."""
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

        # Render each waiting vehicle horizontally with arrows
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

            tk.Label(
                item,
                text=f"🚗 #{vid}",
                bg=COLOR_WAITING_BG,
                fg=COLOR_TEXT_PRIMARY,
                font=("Segoe UI", 9, "bold"),
            ).pack(side="left")

            if idx < len(self._vehicles) - 1:
                tk.Label(
                    self._items_container,
                    text="←",
                    bg=COLOR_BG_CARD,
                    fg=COLOR_WAITING,
                    font=("Segoe UI", 11, "bold"),
                ).pack(side="left", padx=(0, 6))


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
