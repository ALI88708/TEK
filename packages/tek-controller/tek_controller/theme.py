"""Monochrome design tokens for the TEK Controller.

One palette, two typefaces, no colour accents. State is communicated by fill and
weight so the interface stays strictly black / white / neutral grey.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont

PALETTE: dict[str, str] = {
    "bg": "#0A0A0B",
    "panel": "#0E0E10",
    "surface": "#121215",
    "surface_alt": "#17171B",
    "surface_hi": "#1E1E23",
    "border": "#232329",
    "border_strong": "#3A3A44",
    "text": "#F5F5F7",
    "muted": "#9C9CA6",
    "dim": "#66666F",
    "inverse": "#0A0A0B",
    "hover": "#202026",
    "grid_fine": "#141417",
    "grid_coarse": "#1B1B20",
}

UI_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans")
MONO_CANDIDATES = ("Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Courier New")


@dataclass(frozen=True, slots=True)
class Fonts:
    ui: str
    mono: str

    def ui_font(self, size: int = 10, weight: str = "normal") -> tuple[str, int, str]:
        return (self.ui, size, weight)

    def mono_font(self, size: int = 9, weight: str = "normal") -> tuple[str, int, str]:
        return (self.mono, size, weight)


_FONTS: Fonts | None = None


def _pick(root: tk.Misc, candidates: tuple[str, ...], fallback: str) -> str:
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return fallback


def init_fonts(root: tk.Misc) -> Fonts:
    global _FONTS
    _FONTS = Fonts(
        ui=_pick(root, UI_CANDIDATES, "TkDefaultFont"),
        mono=_pick(root, MONO_CANDIDATES, "TkFixedFont"),
    )
    return _FONTS


def fonts() -> Fonts:
    if _FONTS is None:
        return Fonts(ui="TkDefaultFont", mono="TkFixedFont")
    return _FONTS


def enable_windows_dpi_awareness() -> None:
    """Ask Windows for crisp text instead of a bitmap-scaled window."""
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, ImportError, OSError):
        return
