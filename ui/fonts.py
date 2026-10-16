"""Resolve platform-native font families provided by Tk."""

from tkinter import font as tkfont


def font_family(widget, *, fixed: bool = False) -> str:
    """Return Tk's platform-selected proportional or fixed-width family."""
    named_font = "TkFixedFont" if fixed else "TkDefaultFont"
    return tkfont.nametofont(named_font, root=widget).actual("family")
