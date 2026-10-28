"""Public UI widget facade and orchestrator module for the smart parking simulator.

Delegates each visual component to its cohesive submodule inside `ui.components`
while preserving the canonical `ui.widgets` contract required by `AGENTS.md`,
`ui.interface`, and the test suite:
- `ui.components.theme`: color palette (`COLOR_*`), typography helpers, and PNG icon loader
- `ui.components.parking_grid`: `ParkingSlotWidget` and `ParkingLotGridWidget`
- `ui.components.waiting_queue`: `WaitingQueueWidget` (pending requests grouped by slot)
- `ui.components.request_table`: `RequestTrackingTableWidget` (lifecycle tracking table)
- `ui.components.event_log`: `EventLogWidget` (chronological log with non-destructive filters)
- `ui.components.telemetry_bars`: `StatCard`, `MetricsSummaryWidget`, and `ControlBarWidget`
"""

from __future__ import annotations

from ui.components import (
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
    ControlBarWidget,
    EventLogWidget,
    MetricsSummaryWidget,
    PARKING_SPACE_ICON_PATH,
    ParkingLotGridWidget,
    ParkingSlotWidget,
    RequestTrackingTableWidget,
    StatCard,
    WaitingQueueWidget,
    _load_png_icon,
    font_family,
)
from ui.projection import ParkingProjection, RequestRecord, project_occupied_spaces

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
    "ParkingProjection",
    "ParkingSlotWidget",
    "RequestRecord",
    "RequestTrackingTableWidget",
    "StatCard",
    "WaitingQueueWidget",
    "_load_png_icon",
    "font_family",
    "project_occupied_spaces",
]
