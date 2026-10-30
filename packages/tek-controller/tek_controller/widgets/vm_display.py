"""Placeholder surface for the remote guest display.

This is deliberately not a fake desktop. It renders a labelled, gridded viewport
and states plainly that no frames are arriving, because the runtime is not
implemented in this milestone.
"""

from __future__ import annotations

import tkinter as tk

from tek_controller import theme
from tek_controller.session import SessionState

P = theme.PALETTE

_COPY: dict[SessionState, tuple[str, str]] = {
    SessionState.IDLE: ("NO ACTIVE SESSION", "Create a session to attach a display."),
    SessionState.PREPARING: ("PREPARING SESSION", "No runtime link is established yet."),
    SessionState.CONNECTING: ("ATTACHING VIEWER", "No frames received."),
    SessionState.RUNNING: ("AWAITING RUNTIME FRAME", "Runtime integration is not implemented in this build."),
    SessionState.STOPPING: ("SESSION STOPPING", "Display detached."),
    SessionState.FAILED: ("SESSION FAILED", "No display available."),
}


class VmDisplay(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(
            master,
            bg=P["surface"],
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        self._state = SessionState.IDLE
        self._grid_visible = True
        self._scale = 100
        self._fit = True

        self.canvas = tk.Canvas(
            self,
            bg="#0C0C0E",
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw())

    def set_state(self, state: SessionState) -> None:
        self._state = state
        self._draw()

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self._draw()

    def set_scale(self, percent: int) -> None:
        self._scale = percent
        self._draw()

    def set_fit(self, fit: bool) -> None:
        self._fit = fit
        self._draw()

    def _draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")

        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 2 or height <= 2:
            return

        fonts = theme.fonts()

        if self._grid_visible:
            spacing = 32
            for x in range(0, width, spacing):
                coarse = (x // spacing) % 4 == 0
                canvas.create_line(
                    x, 0, x, height,
                    fill=P["grid_coarse"] if coarse else P["grid_fine"],
                )
            for y in range(0, height, spacing):
                coarse = (y // spacing) % 4 == 0
                canvas.create_line(
                    0, y, width, y,
                    fill=P["grid_coarse"] if coarse else P["grid_fine"],
                )

        arm = 14
        margin = 18
        corners = (
            (margin, margin, 1, 1),
            (width - margin, margin, -1, 1),
            (margin, height - margin, 1, -1),
            (width - margin, height - margin, -1, -1),
        )
        for cx, cy, dx, dy in corners:
            canvas.create_line(cx, cy, cx + arm * dx, cy, fill=P["border_strong"])
            canvas.create_line(cx, cy, cx, cy + arm * dy, fill=P["border_strong"])

        canvas.create_text(
            24, 20,
            text="DISPLAY",
            anchor="nw",
            fill=P["dim"],
            font=fonts.mono_font(8, "bold"),
        )

        badge = "OFFLINE" if self._state is SessionState.IDLE else self._state.value.upper()
        canvas.create_text(
            width - 24, 20,
            text=badge,
            anchor="ne",
            fill=P["dim"],
            font=fonts.mono_font(8, "bold"),
        )

        title, subtitle = _COPY[self._state]
        canvas.create_text(
            width / 2, height / 2 - 10,
            text=title,
            fill=P["muted"],
            font=fonts.mono_font(12, "bold"),
        )
        canvas.create_text(
            width / 2, height / 2 + 16,
            text=subtitle,
            fill=P["dim"],
            font=fonts.ui_font(9),
        )

        canvas.create_line(
            width / 2 - 40, height / 2 - 34,
            width / 2 + 40, height / 2 - 34,
            fill=P["border"],
        )

        canvas.create_text(
            24, height - 20,
            text=(
                f"TRANSPORT  VNC   /   FIT  {'ON' if self._fit else 'OFF'}"
                f"   /   SCALE  {self._scale}%"
            ),
            anchor="sw",
            fill=P["dim"],
            font=fonts.mono_font(8),
        )
        canvas.create_text(
            width - 24, height - 20,
            text="PROTOCOL  tek/0",
            anchor="se",
            fill=P["dim"],
            font=fonts.mono_font(8),
        )
