"""Chronological concurrency event log widget with non-destructive view filters."""

from __future__ import annotations

from collections import deque
import re
import tkinter as tk
from tkinter import ttk
from typing import Any

from ui.components.theme import (
    COLOR_AVAILABLE,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_LOG_BG,
    COLOR_OCCUPIED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    font_family,
)


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

    def __init__(
        self, parent: tk.Widget, max_lines: int = DEFAULT_MAX_LINES, **kwargs
    ) -> None:
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
        self._font_size = tk.IntVar(master=self, value=13)

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

        font_control = tk.Frame(header, bg=COLOR_BG_CARD)
        font_control.pack(side="right", padx=(0, 8))
        tk.Label(
            font_control, text="Fuente:", bg=COLOR_BG_CARD, fg=COLOR_TEXT_MUTED,
            font=(font_family(self), 8),
        ).pack(side="left", padx=(0, 4))
        self._combo_font_size = ttk.Combobox(
            font_control, textvariable=self._font_size, values=(10, 12, 13, 14),
            state="readonly", width=3, font=(font_family(self), 8),
        )
        self._combo_font_size.pack(side="left")
        self._combo_font_size.bind("<<ComboboxSelected>>", self._apply_font_size)

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
            font=(font_family(self, fixed=True), 13),
            wrap="word",
            state="disabled",
            yscrollcommand=self._scrollbar.set,
            relief="flat",
            padx=8,
            pady=8,
            spacing1=2,
        )
        self._text.pack(side="left", fill="both", expand=True)
        self._scrollbar.config(command=self._text.yview)

        # Event color tags for visual clarity
        self._text.tag_config("TIME", foreground=COLOR_TEXT_MUTED)
        self._text.tag_config("CREATED", foreground="#cbd5e1")
        self._text.tag_config("WAITING", foreground=COLOR_WAITING)
        self._text.tag_config("ENTERED", foreground=COLOR_AVAILABLE)
        self._text.tag_config("EXITED", foreground=COLOR_INFO)
        self._text.tag_config("FINISHED", foreground=COLOR_TEXT_MUTED)
        self._text.tag_config("REJECTED", foreground=COLOR_OCCUPIED)
        self._text.tag_config("CANCELLED", foreground="#fb923c")
        self._text.tag_config(
            "ERROR", foreground=COLOR_OCCUPIED, font=(font_family(self, fixed=True), 13, "bold")
        )
        self._text.tag_config(
            "SYSTEM", foreground=COLOR_INFO, font=(font_family(self, fixed=True), 13, "bold")
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

    def _apply_font_size(self, _event=None) -> None:
        """Apply the selected size to existing and subsequently rendered log text."""
        size = int(self._font_size.get())
        fixed = font_family(self, fixed=True)
        self._text.config(font=(fixed, size))
        for tag in ("ERROR", "SYSTEM"):
            self._text.tag_config(tag, font=(fixed, size, "bold"))

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


__all__ = ["EventLogWidget"]
