"""Local preferences: display, connection, and where they are stored."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path

from tek_controller import theme
from tek_controller.settings import (
    SCALE_CHOICES,
    TIMEOUT_MAX_S,
    TIMEOUT_MIN_S,
    Settings,
)
from tek_controller.widgets.primitives import (
    ActionButton,
    Card,
    CheckRow,
    Divider,
    LabeledEntry,
    SectionHeader,
    SegmentedControl,
)

P = theme.PALETTE


def _elide_directory(path: Path, limit: int = 32) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return "..." + text[-(limit - 3):]


class SettingsView(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        settings_path: Path,
        on_save: Callable[[], object],
        on_restore: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=P["bg"])
        self.columnconfigure(0, weight=1, uniform="settings")
        self.columnconfigure(1, weight=1, uniform="settings")
        self.columnconfigure(2, weight=0, minsize=300)

        self._build_display()
        self._build_connection()
        self._build_storage(settings_path)

        actions = tk.Frame(self, bg=P["bg"])
        actions.grid(row=1, column=0, columnspan=2, sticky="w", pady=(16, 0))

        ActionButton(actions, "Save Preferences", on_save, variant="primary").pack(
            side="left"
        )
        ActionButton(
            actions, "Restore Defaults", on_restore, variant="secondary"
        ).pack(side="left", padx=(8, 0))

        self.status_label = tk.Label(
            self,
            text="",
            bg=P["bg"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=620,
        )
        self.status_label.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0)
        )

    def _build_display(self) -> None:
        card = Card(self)
        card.grid(row=0, column=0, sticky="new", padx=(0, 16))

        SectionHeader(card.body, "01", "Display").pack(fill="x")

        self.fit_row = CheckRow(
            card.body,
            "Fit display to window",
            hint="Scale incoming frames to the viewport instead of cropping.",
            wrap=220,
        )
        self.fit_row.pack(fill="x", pady=(14, 0))
        self.fit_var = self.fit_row.var

        tk.Label(
            card.body,
            text="VIEWPORT SCALE",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().mono_font(8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(16, 6))

        self.scale_control = SegmentedControl(card.body, SCALE_CHOICES)
        self.scale_control.pack(anchor="w")
        self.scale_var = self.scale_control.var

        self.grid_row = CheckRow(
            card.body,
            "Show alignment grid",
            hint="The grid is a placeholder guide until frames arrive.",
            wrap=220,
        )
        self.grid_row.pack(fill="x", pady=(16, 0))
        self.grid_var = self.grid_row.var

    def _build_connection(self) -> None:
        card = Card(self)
        card.grid(row=0, column=1, sticky="new", padx=(0, 16))

        SectionHeader(card.body, "02", "Connection").pack(fill="x")

        self.timeout_field = LabeledEntry(
            card.body,
            "Connect timeout (seconds)",
            hint=f"Whole seconds, {TIMEOUT_MIN_S} to {TIMEOUT_MAX_S}.",
        )
        self.timeout_field.pack(fill="x", pady=(14, 0))
        self.timeout_var = self.timeout_field.var

        self.verify_row = CheckRow(
            card.body,
            "Reject expired descriptors",
            hint="Checked locally against the system clock.",
            wrap=220,
        )
        self.verify_row.pack(fill="x", pady=(16, 0))
        self.verify_var = self.verify_row.var

        Divider(card.body).pack(fill="x", pady=14)

        tk.Label(
            card.body,
            text=(
                "These preferences are local to this controller. Nothing here "
                "is sent to a runtime or stored with a session."
            ),
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=220,
        ).pack(fill="x")

    def _build_storage(self, settings_path: Path) -> None:
        card = Card(self)
        card.grid(row=0, column=2, sticky="new")

        SectionHeader(card.body, "03", "Storage").pack(fill="x")

        tk.Label(
            card.body,
            text="This file holds preferences only. It never holds a session "
            "secret, token, or descriptor.",
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
            wraplength=240,
        ).pack(fill="x", pady=(12, 14))

        path_box = tk.Frame(
            card.body,
            bg=P["surface_alt"],
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        path_box.pack(fill="x")

        self.path_label = tk.Label(
            path_box,
            text=_elide_directory(settings_path.parent),
            bg=P["surface_alt"],
            fg=P["dim"],
            font=theme.fonts().mono_font(8),
            anchor="w",
            padx=10,
        )
        self.path_label.pack(fill="x", pady=(8, 0))

        tk.Label(
            path_box,
            text=settings_path.name,
            bg=P["surface_alt"],
            fg=P["text"],
            font=theme.fonts().mono_font(8, "bold"),
            anchor="w",
            padx=10,
        ).pack(fill="x", pady=(2, 8))

        tk.Label(
            card.body,
            text=(
                "Runtime transport, viewer streaming, and input forwarding are "
                "not implemented in this prototype."
            ),
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=240,
        ).pack(fill="x", pady=(14, 0))

    # -- state -----------------------------------------------------------

    def load(self, settings: Settings) -> None:
        self.fit_var.set(settings.fit_display)
        self.scale_control.set(settings.scale_percent)
        self.grid_var.set(settings.show_grid)
        self.timeout_var.set(str(settings.connect_timeout_s))
        self.verify_var.set(settings.verify_expiry)

    def timeout_value(self) -> int | None:
        text = self.timeout_var.get().strip()
        try:
            value = int(text)
        except ValueError:
            return None
        if not TIMEOUT_MIN_S <= value <= TIMEOUT_MAX_S:
            return None
        return value

    def set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.configure(text=text, fg=P["text"] if error else P["dim"])
