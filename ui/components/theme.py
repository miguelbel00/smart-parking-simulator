"""Shared color palette, typography helpers, and PNG asset loaders for UI components."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk

from ui.fonts import font_family

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
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
    "PARKING_SPACE_ICON_PATH",
    "_load_png_icon",
    "font_family",
]
