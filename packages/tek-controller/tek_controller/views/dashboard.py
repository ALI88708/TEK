"""Session dashboard: control surface, runtime link, display, event log."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import UTC, datetime

from tek_controller import theme
from tek_controller.session import STATE_HINTS, SessionState
from tek_controller.widgets.primitives import (
    ActionButton,
    Card,
    Divider,
    KeyValueRow,
    SectionHeader,
    StageRail,
)
from tek_controller.widgets.vm_display import VmDisplay

P = theme.PALETTE


class DashboardView(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_create: Callable[[], None],
        on_open_connection: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=P["bg"])
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0, minsize=372)
        self.rowconfigure(0, weight=1)

        left = tk.Frame(self, bg=P["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        right = tk.Frame(self, bg=P["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_display(left)
        self._build_log(left)
        self._build_session_card(right, on_create, on_open_connection)
        self._build_runtime_card(right)

    # -- construction ----------------------------------------------------

    def _build_display(self, master: tk.Misc) -> None:
        card = Card(master)
        card.grid(row=0, column=0, sticky="nsew")

        SectionHeader(card.body, "01", "Display").pack(fill="x")

        self.display = VmDisplay(card.body)
        self.display.pack(fill="both", expand=True, pady=(14, 0))

    def _build_log(self, master: tk.Misc) -> None:
        card = Card(master, padding=16)
        card.grid(row=1, column=0, sticky="ew", pady=(16, 0))

        header = tk.Frame(card.body, bg=P["surface"])
        header.pack(fill="x")

        SectionHeader(header, "02", "Event log").pack(
            side="left", fill="x", expand=True
        )
        ActionButton(
            header,
            "Clear",
            self.clear_log,
            variant="ghost",
        ).pack(side="right", padx=(12, 0))

        self.event_log = tk.Text(
            card.body,
            height=6,
            bg=P["surface_alt"],
            fg=P["muted"],
            insertbackground=P["muted"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["border"],
            font=theme.fonts().mono_font(8),
            padx=10,
            pady=8,
            wrap="none",
            state="disabled",
        )
        self.event_log.pack(fill="both", expand=True, pady=(12, 0))

    def _build_session_card(
        self,
        master: tk.Misc,
        on_create: Callable[[], None],
        on_open_connection: Callable[[], None],
    ) -> None:
        card = Card(master, padding=16)
        card.grid(row=0, column=0, sticky="new")

        SectionHeader(card.body, "01", "Session").pack(fill="x")

        tk.Label(
            card.body,
            text="CURRENT STATE",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().mono_font(8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(10, 2))

        self.state_label = tk.Label(
            card.body,
            text=SessionState.IDLE.value,
            bg=P["surface"],
            fg=P["text"],
            font=theme.fonts().ui_font(19, "bold"),
            anchor="w",
        )
        self.state_label.pack(fill="x")

        self.rail = StageRail(card.body)
        self.rail.pack(fill="x", pady=(6, 6))

        self.hint_label = tk.Label(
            card.body,
            text=STATE_HINTS[SessionState.IDLE],
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
            wraplength=300,
        )
        self.hint_label.pack(fill="x")

        Divider(card.body).pack(fill="x", pady=10)

        self.session_id_label = self._row(card.body, "SESSION ID")
        self.runtime_label = self._row(card.body, "RUNTIME")
        self.protocol_label = self._row(card.body, "PROTOCOL")
        self.protocol_label.set("tek/0")

        ActionButton(
            card.body, "Create Session", on_create, variant="primary"
        ).pack(fill="x", pady=(12, 0))
        ActionButton(
            card.body, "Open Connection", on_open_connection, variant="secondary"
        ).pack(fill="x", pady=(6, 0))

        self.notice_label = tk.Label(
            card.body,
            text="No session. Nothing is running and nothing is reserved.",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=300,
        )
        self.notice_label.pack(fill="x", pady=(10, 0))

    def _build_runtime_card(self, master: tk.Misc) -> None:
        card = Card(master, padding=16)
        card.grid(row=1, column=0, sticky="ew", pady=(16, 0))

        SectionHeader(card.body, "02", "Runtime").pack(fill="x")

        status = tk.Frame(card.body, bg=P["surface"])
        status.pack(fill="x", pady=(12, 0))

        self.runtime_status_label = tk.Label(
            status,
            text="NOT CONNECTED",
            bg=P["surface"],
            fg=P["text"],
            font=theme.fonts().mono_font(9, "bold"),
            anchor="w",
        )
        self.runtime_status_label.pack(side="left")

        tk.Label(
            status,
            text="NOT IMPLEMENTED",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().mono_font(8),
            anchor="e",
        ).pack(side="right")

    def _row(self, master: tk.Misc, label: str) -> KeyValueRow:
        row = KeyValueRow(master, label)
        row.pack(fill="x", pady=3)
        return row

    # -- updates ---------------------------------------------------------

    def set_state(self, state: SessionState) -> None:
        self.state_label.configure(text=state.value)
        self.rail.set_state(state)
        self.hint_label.configure(text=STATE_HINTS[state])
        self.display.set_state(state)

    def set_session_id(self, value: str) -> None:
        self.session_id_label.set(value)

    def set_runtime(self, value: str) -> None:
        self.runtime_label.set(value)

    def set_runtime_status(self, value: str) -> None:
        self.runtime_status_label.configure(text=value.upper())

    def set_notice(self, text: str) -> None:
        self.notice_label.configure(text=text)

    def log(self, message: str) -> None:
        stamp = datetime.now(UTC).astimezone().strftime("%H:%M:%S")
        self.event_log.configure(state="normal")
        self.event_log.insert("end", f"{stamp}  {message}\n")
        self.event_log.see("end")
        self.event_log.configure(state="disabled")

    def clear_log(self) -> None:
        self.event_log.configure(state="normal")
        self.event_log.delete("1.0", "end")
        self.event_log.configure(state="disabled")
