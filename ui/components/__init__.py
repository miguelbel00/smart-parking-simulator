"""Modular Tkinter UI components for the smart parking simulator."""

from ui.components.event_log import EventLogWidget
from ui.components.parking_grid import ParkingLotGridWidget, ParkingSlotWidget
from ui.components.request_table import RequestTrackingTableWidget
from ui.components.telemetry_bars import (
    ControlBarWidget,
    MetricsSummaryWidget,
    StatCard,
)
from ui.components.theme import (
    ASSETS_DIR,
    CAR_OCCUPIED_ICON_PATH,
    COLOR_AVAILABLE,
    COLOR_AVAILABLE_BG,
    COLOR_BG_CARD,
    COLOR_BG_PRIMARY,
    COLOR_BORDER,
    COLOR_INFO,
    COLOR_INFO_BG,
    COLOR_LOG_BG,
    COLOR_OCCUPIED,
    COLOR_OCCUPIED_BG,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_WAITING,
    COLOR_WAITING_BG,
    PARKING_SPACE_ICON_PATH,
    _load_png_icon,
    font_family,
)
from ui.components.waiting_queue import WaitingQueueWidget

__all__ = [
    "ASSETS_DIR",
    "CAR_OCCUPIED_ICON_PATH",
    "COLOR_AVAILABLE",
    "COLOR_AVAILABLE_BG",
    "COLOR_BG_CARD",
    "COLOR_BG_PRIMARY",
    "COLOR_BORDER",
    "COLOR_INFO",
    "COLOR_INFO_BG",
    "COLOR_LOG_BG",
    "COLOR_OCCUPIED",
    "COLOR_OCCUPIED_BG",
    "COLOR_TEXT_MUTED",
    "COLOR_TEXT_PRIMARY",
    "COLOR_WAITING",
    "COLOR_WAITING_BG",
    "ControlBarWidget",
    "EventLogWidget",
    "MetricsSummaryWidget",
    "PARKING_SPACE_ICON_PATH",
    "ParkingLotGridWidget",
    "ParkingSlotWidget",
    "RequestTrackingTableWidget",
    "StatCard",
    "WaitingQueueWidget",
    "_load_png_icon",
    "font_family",
]
