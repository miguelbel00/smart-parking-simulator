"""CustomTkinter components for the parking monitor.

The parking diagram uses a standard Tk Canvas for precise schematic drawing;
all surrounding controls and panels use CustomTkinter widgets.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable

import customtkinter as ctk

COLOR_BG_PRIMARY = "#0f172a"
COLOR_BG_CARD = "#1e293b"
COLOR_BORDER = "#334155"
COLOR_TEXT_PRIMARY = "#f8fafc"
COLOR_TEXT_MUTED = "#94a3b8"
COLOR_AVAILABLE = "#10b981"
COLOR_AVAILABLE_BG = "#064e3b"
COLOR_OCCUPIED = "#ef4444"
COLOR_OCCUPIED_BG = "#7f1d1d"
COLOR_WAITING = "#f59e0b"
COLOR_WAITING_BG = "#78350f"
COLOR_INFO = "#38bdf8"
COLOR_LOG_BG = "#050811"
WAITING_PREVIEW_LIMIT = 5
# CustomTkinter bundles Roboto; unlike TkDefaultFont this does not inherit a
# platform alias that may resolve to a small or monospaced fallback.
UI_FONT = "Roboto"


def diagram_transform(content_width: float, content_height: float,
                      viewport_width: float, viewport_height: float,
                      allow_vertical_scroll: bool = False) -> tuple[float, float, float]:
    """Return a uniform scale and centering offsets."""
    if min(content_width, content_height, viewport_width, viewport_height) <= 0:
        return 1.0, 0.0, 0.0
    width_scale = viewport_width / content_width
    height_scale = viewport_height / content_height
    scale = width_scale if allow_vertical_scroll else min(width_scale, height_scale)
    return (scale, (viewport_width - content_width * scale) / 2,
            max(0.0, (viewport_height - content_height * scale) / 2))


def diagram_font_size(base_size: int, scale: float) -> int:
    """Keep Canvas labels proportional without shrinking below a legible minimum."""
    return max(8, round(base_size * scale))


def waiting_queue_preview(vehicle_ids: Iterable[int], limit: int = WAITING_PREVIEW_LIMIT) -> str:
    """Format a bounded preview without changing the source queue."""
    ids = tuple(vehicle_ids)
    visible = ids[:limit]
    preview = "  ·  ".join(f"#{vehicle_id}" for vehicle_id in visible)
    overflow = len(ids) - len(visible)
    return f"{preview}  ·  +{overflow} más" if overflow else preview


class StatCard(ctk.CTkFrame):
    def __init__(self, parent, title: str, initial_value: str = "0", subtitle: str = "",
                 value_color: str = COLOR_TEXT_PRIMARY, **kwargs) -> None:
        super().__init__(parent, fg_color=COLOR_BG_PRIMARY, border_width=0,
                         corner_radius=0, **kwargs)
        self.value_color = value_color
        ctk.CTkLabel(self, text=title.upper(), text_color=COLOR_TEXT_MUTED,
                     font=(UI_FONT, 12, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        self._lbl_value = ctk.CTkLabel(self, text=initial_value, text_color=value_color,
                                       font=(UI_FONT, 28, "bold"), anchor="w")
        self._lbl_value.pack(fill="x", padx=12, pady=(0, 0))
        self._lbl_subtitle = ctk.CTkLabel(self, text=subtitle, text_color=COLOR_TEXT_MUTED,
                                          font=(UI_FONT, 11), anchor="w")
        if subtitle:
            self._lbl_subtitle.pack(fill="x", padx=12, pady=(0, 8))

    def update_value(self, value: str | int, subtitle: str | None = None) -> None:
        self._lbl_value.configure(text=str(value))
        if subtitle is not None:
            self._lbl_subtitle.configure(text=subtitle)


class ParkingLotGridWidget(ctk.CTkFrame):
    """Top-down parking layout with facing banks and a central aisle."""

    SLOT_WIDTH = 92
    ROW_HEIGHT = 112
    PADDING = 16
    AISLE_HEIGHT = 72

    def __init__(self, parent, columns: int = 5, **kwargs) -> None:
        super().__init__(parent, fg_color=COLOR_BG_PRIMARY, **kwargs)
        self.columns = columns
        self.slots: dict[int, dict[str, int | tuple[int, ...]]] = {}
        self._content_size = (0, 0)
        self._allow_vertical_scroll = False
        self._render_scale = 1.0
        self._render_x = 0.0
        self._render_y = 0.0
        self._text_base_sizes: dict[int, int] = {}
        self.canvas = tk.Canvas(self, bg=COLOR_BG_PRIMARY, highlightthickness=0,
                                yscrollincrement=self.ROW_HEIGHT)
        scrollbar = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._resize_diagram)

    def _resize_diagram(self, _event=None) -> None:
        width, height = self._content_size
        if not width or not height:
            return
        scale, offset_x, offset_y = diagram_transform(
            width, height, self.canvas.winfo_width(), self.canvas.winfo_height(),
            allow_vertical_scroll=self._allow_vertical_scroll,
        )
        ratio = scale / self._render_scale
        self.canvas.scale("diagram", 0, 0, ratio, ratio)
        self.canvas.move("diagram", offset_x - self._render_x * ratio,
                         offset_y - self._render_y * ratio)
        for item, base_size in self._text_base_sizes.items():
            self.canvas.itemconfigure(item, font=(UI_FONT, diagram_font_size(base_size, scale), "bold"))
        self._render_scale, self._render_x, self._render_y = scale, offset_x, offset_y
        self.canvas.configure(scrollregion=(0, 0, max(self.canvas.winfo_width(), width * scale),
                                            max(self.canvas.winfo_height(), height * scale)))

    @classmethod
    def slot_bounds(cls, space_id: int, columns: int = 5) -> tuple[int, int, int, int]:
        zero_based = space_id - 1
        bank_row, position = divmod(zero_based, columns * 2)
        bank_column = position % columns
        x = cls.PADDING + bank_column * cls.SLOT_WIDTH
        y = cls.PADDING + bank_row * (2 * cls.ROW_HEIGHT + cls.AISLE_HEIGHT)
        if position >= columns:
            y += cls.ROW_HEIGHT + cls.AISLE_HEIGHT
        return x, y, x + cls.SLOT_WIDTH - 4, y + cls.ROW_HEIGHT - 4

    def setup_slots(self, capacity: int) -> None:
        self.canvas.delete("all")
        self.slots.clear()
        self._text_base_sizes.clear()
        self._render_scale, self._render_x, self._render_y = 1.0, 0.0, 0.0
        rows = (capacity + self.columns * 2 - 1) // (self.columns * 2)
        self._allow_vertical_scroll = rows > 1
        width = self.PADDING * 2 + self.columns * self.SLOT_WIDTH
        height = self.PADDING * 2 + rows * (2 * self.ROW_HEIGHT + self.AISLE_HEIGHT)
        for row in range(rows):
            top = self.PADDING + row * (2 * self.ROW_HEIGHT + self.AISLE_HEIGHT) + self.ROW_HEIGHT
            bottom = top + self.AISLE_HEIGHT
            self.canvas.create_rectangle(0, top, width, bottom, fill="#172235", outline="", tags="diagram")
            for x in range(12, width, 32):
                self.canvas.create_line(x, (top + bottom) // 2, x + 16, (top + bottom) // 2,
                                        fill="#fbbf24", width=2, tags="diagram")
            self.canvas.create_text(width - 8, top + 8, text="CIRCULACIÓN", fill=COLOR_TEXT_MUTED,
                                    anchor="ne", font=(UI_FONT, 13, "bold"), tags=("diagram", "diagram_text"))
            self.canvas.create_text(width - 8, bottom - 8, text="ENTRADA / SALIDA",
                                    fill=COLOR_INFO, anchor="se", font=(UI_FONT, 13, "bold"),
                                    tags=("diagram", "diagram_text"))
        for space_id in range(1, capacity + 1):
            x1, y1, x2, y2 = self.slot_bounds(space_id, self.columns)
            rect = self.canvas.create_rectangle(x1, y1, x2, y2, fill="#263449", outline="#64748b", width=2, tags="diagram")
            self.canvas.create_line(x1, y1, x2, y1, fill=COLOR_TEXT_PRIMARY, width=2, dash=(5, 4), tags="diagram")
            self.canvas.create_line(x1, y2, x2, y2, fill=COLOR_TEXT_PRIMARY, width=2, dash=(5, 4), tags="diagram")
            car = self._draw_car(x1 + 18, y1 + 20, x2 - 18, y2 - 20, COLOR_AVAILABLE_BG, COLOR_AVAILABLE)
            label = self.canvas.create_text(x1 + 4, y1 + 3, text=f"#{space_id}", fill=COLOR_TEXT_PRIMARY,
                                            anchor="nw", font=(UI_FONT, 13, "bold"), tags=("diagram", "diagram_text"))
            detail = self.canvas.create_text(x1 + 4, y2 - 4, text="LIBRE", fill=COLOR_AVAILABLE,
                                             anchor="sw", font=(UI_FONT, 12, "bold"), tags=("diagram", "diagram_text"))
            self.slots[space_id] = {"rect": rect, "label": label, "detail": detail, "car": car}
            self._text_base_sizes[label] = 13
            self._text_base_sizes[detail] = 12
        for item in self.canvas.find_withtag("diagram_text"):
            if item not in self._text_base_sizes:
                self._text_base_sizes[item] = 13
        self.canvas.addtag_withtag("diagram", "all")
        self._content_size = width, height
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._resize_diagram()

    def _draw_car(self, x1: int, y1: int, x2: int, y2: int, fill: str, outline: str) -> tuple[int, ...]:
        body = self.canvas.create_polygon(x1 + 8, y1, x2 - 8, y1, x2, y1 + 10, x2, y2 - 10,
                                          x2 - 8, y2, x1 + 8, y2, x1, y2 - 10, x1, y1 + 10,
                                          smooth=True, splinesteps=8, fill=fill, outline=outline, width=2, tags="diagram")
        window = self.canvas.create_rectangle(x1 + 5, y1 + 9, x2 - 5, y2 - 9, fill="#94a3b8", outline="", tags="diagram")
        center = self.canvas.create_line((x1 + x2) // 2, y1 + 9, (x1 + x2) // 2, y2 - 9,
                                         fill="#475569", width=2, tags="diagram")
        return body, window, center

    def occupy_slot(self, space_id: int, vehicle_id: int) -> None:
        if space_id not in self.slots:
            return
        slot = self.slots[space_id]
        self.canvas.itemconfigure(slot["rect"], fill=COLOR_OCCUPIED_BG, outline=COLOR_OCCUPIED)
        self.canvas.itemconfigure(slot["label"], fill=COLOR_OCCUPIED)
        self.canvas.itemconfigure(slot["detail"], text=f"Auto #{vehicle_id}", fill=COLOR_OCCUPIED)
        car = slot.get("car")
        if car:
            body, window, center = car
            self.canvas.itemconfigure(body, fill=COLOR_OCCUPIED_BG, outline=COLOR_OCCUPIED)
            self.canvas.itemconfigure(window, fill="#94a3b8")
            self.canvas.itemconfigure(center, fill="#475569")

    def free_slot(self, space_id: int) -> None:
        if space_id not in self.slots:
            return
        slot = self.slots[space_id]
        self.canvas.itemconfigure(slot["rect"], fill=COLOR_AVAILABLE_BG, outline=COLOR_AVAILABLE)
        self.canvas.itemconfigure(slot["label"], fill=COLOR_AVAILABLE)
        self.canvas.itemconfigure(slot["detail"], text="LIBRE", fill=COLOR_AVAILABLE)
        car = slot.get("car")
        if car:
            body, window, center = car
            self.canvas.itemconfigure(body, fill=COLOR_AVAILABLE_BG, outline=COLOR_AVAILABLE)
            self.canvas.itemconfigure(window, fill="#94a3b8")
            self.canvas.itemconfigure(center, fill="#475569")

    def sync_from_snapshot(self, occupied_spaces: Iterable[tuple[int, int]]) -> None:
        occupied = {space_id + 1: vehicle_id for space_id, vehicle_id in occupied_spaces}
        for space_id in self.slots:
            self.occupy_slot(space_id, occupied[space_id]) if space_id in occupied else self.free_slot(space_id)

    def reset(self) -> None:
        for space_id in self.slots:
            self.free_slot(space_id)


class WaitingQueueWidget(ctk.CTkFrame):
    def __init__(self, parent, **kwargs) -> None:
        super().__init__(parent, fg_color=COLOR_BG_PRIMARY, border_width=0,
                         corner_radius=0, **kwargs)
        self._vehicles: list[int] = []
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(header, text="Vehículos en espera", text_color=COLOR_WAITING,
                     font=(UI_FONT, 14, "bold")).pack(side="left")
        self._lbl_count = ctk.CTkLabel(header, text="0 vehículos", fg_color="transparent",
                                       text_color=COLOR_WAITING, corner_radius=0,
                                        font=(UI_FONT, 12, "bold"))
        self._lbl_count.pack(side="right")
        self._items_container = ctk.CTkFrame(self, fg_color="transparent")
        self._items_container.pack(fill="x", padx=14, pady=(6, 10))
        self._refresh()

    def add_vehicle(self, vehicle_id: int) -> None:
        if vehicle_id not in self._vehicles:
            self._vehicles.append(vehicle_id)
            self._refresh()

    def remove_vehicle(self, vehicle_id: int) -> None:
        if vehicle_id in self._vehicles:
            self._vehicles.remove(vehicle_id)
            self._refresh()

    def clear(self) -> None:
        self._vehicles.clear()
        self._refresh()

    def _refresh(self) -> None:
        count = len(self._vehicles)
        self._lbl_count.configure(text=f"{count} vehículo{'s' if count != 1 else ''}")
        for child in self._items_container.winfo_children():
            child.destroy()
        text = waiting_queue_preview(self._vehicles) if self._vehicles else "No hay vehículos en espera."
        ctk.CTkLabel(self._items_container, text=text, text_color=COLOR_TEXT_PRIMARY if count else COLOR_TEXT_MUTED,
                      fg_color=COLOR_WAITING_BG if count else "transparent", corner_radius=0,
                      anchor="w", font=(UI_FONT, 12, "bold" if count else "normal"),
                     padx=10, pady=7).pack(fill="x")


class EventLogWidget(ctk.CTkFrame):
    """Compact diagnostic log; secondary to the parking map."""
    def __init__(self, parent, **kwargs) -> None:
        super().__init__(parent, fg_color=COLOR_BG_CARD, border_width=0,
                         corner_radius=0, **kwargs)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(9, 5))
        ctk.CTkLabel(header, text="Registro de eventos", text_color=COLOR_TEXT_PRIMARY,
                     font=(UI_FONT, 14, "bold")).pack(side="left")
        ctk.CTkButton(header, text="Limpiar", width=78, height=32, corner_radius=0,
                      fg_color=COLOR_BORDER, hover_color="#475569", command=self.clear).pack(side="right")
        self._text = ctk.CTkTextbox(self, fg_color=COLOR_LOG_BG, text_color=COLOR_TEXT_PRIMARY,
                                    font=(UI_FONT, 12), wrap="word", activate_scrollbars=True)
        self._text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._text.configure(state="disabled")

    def log(self, event_type: str, message: str, timestamp_str: str) -> None:
        self._text.configure(state="normal")
        self._text.insert("end", f"[{timestamp_str}] [{event_type}] {message}\n")
        self._text.see("end")
        self._text.configure(state="disabled")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


class ControlBarWidget(ctk.CTkFrame):
    def __init__(self, parent, on_start: Callable[[], None] | None = None,
                 on_stop: Callable[[], None] | None = None, **kwargs) -> None:
        super().__init__(parent, fg_color=COLOR_BG_CARD, corner_radius=0, border_width=0, **kwargs)
        self.on_start, self.on_stop = on_start, on_stop
        title_box = ctk.CTkFrame(self, fg_color="transparent")
        title_box.pack(side="left", padx=16, pady=12)
        ctk.CTkLabel(title_box, text="Smart Parking Simulator", text_color=COLOR_TEXT_PRIMARY,
                     font=(UI_FONT, 20, "bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Monitor de concurrencia y sincronización", text_color=COLOR_TEXT_MUTED,
                     font=(UI_FONT, 12)).pack(anchor="w")
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(side="right", padx=16, pady=12)
        self._lbl_status = ctk.CTkLabel(buttons, text="DETENIDA", fg_color="transparent",
                                        text_color=COLOR_TEXT_MUTED, corner_radius=0,
                                        font=(UI_FONT, 12, "bold"), padx=10, pady=6)
        self._lbl_status.pack(side="left", padx=(0, 12))
        self._btn_start = ctk.CTkButton(buttons, text="Iniciar simulación", width=160, height=38,
                                        corner_radius=0, fg_color=COLOR_AVAILABLE_BG, hover_color="#047857",
                                        command=self._handle_start)
        self._btn_start.pack(side="left", padx=(0, 8))
        self._btn_stop = ctk.CTkButton(buttons, text="Detener", width=110, height=38,
                                       corner_radius=0, fg_color=COLOR_OCCUPIED_BG, hover_color="#991b1b",
                                       command=self._handle_stop, state="disabled")
        self._btn_stop.pack(side="left")

    def _handle_start(self) -> None:
        if self.on_start:
            self.on_start()

    def _handle_stop(self) -> None:
        if self.on_stop:
            self.on_stop()

    def set_running(self) -> None:
        self._lbl_status.configure(text="EN EJECUCIÓN", fg_color=COLOR_AVAILABLE_BG, text_color=COLOR_AVAILABLE)
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")

    def set_stopped(self) -> None:
        self._lbl_status.configure(text="FINALIZADA", fg_color=COLOR_BORDER, text_color=COLOR_INFO)
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
