"""Manual connection view: paste a descriptor, validate it, attempt connect."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from tek_controller import theme
from tek_controller.widgets.primitives import (
    ActionButton,
    Card,
    Divider,
    KeyValueRow,
    SectionHeader,
)

P = theme.PALETTE


class ConnectionView(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_connect: Callable[[], object],
        on_clear: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=P["bg"])
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0, minsize=340)
        self.rowconfigure(0, weight=1)

        self._build_input(self, on_connect, on_clear)

        right = tk.Frame(self, bg=P["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_summary(right)
        self._build_validation(right)

    def _build_input(
        self,
        master: tk.Misc,
        on_connect: Callable[[], object],
        on_clear: Callable[[], None],
    ) -> None:
        card = Card(master)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        SectionHeader(card.body, "01", "Session descriptor").pack(fill="x")

        tk.Label(
            card.body,
            text=(
                "Paste the descriptor JSON served by the runtime at "
                "/tek/descriptor. The controller validates it locally; this build "
                "does not fetch it and does not open a viewer."
            ),
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
            wraplength=560,
        ).pack(fill="x", pady=(12, 0))

        self.descriptor_input = tk.Text(
            card.body,
            height=11,
            bg=P["surface_alt"],
            fg=P["text"],
            insertbackground=P["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["border_strong"],
            font=theme.fonts().mono_font(9),
            padx=12,
            pady=10,
            wrap="word",
            undo=True,
        )
        self.descriptor_input.pack(fill="both", expand=True, pady=(14, 0))

        tk.Label(
            card.body,
            text=(
                "Descriptor only. Do not paste a session secret, password, or "
                "bearer token here. This field is never written to disk."
            ),
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=560,
        ).pack(fill="x", pady=(10, 0))

        actions = tk.Frame(card.body, bg=P["surface"])
        actions.pack(fill="x", pady=(16, 0))

        ActionButton(actions, "Connect", on_connect, variant="primary").pack(
            side="left"
        )
        ActionButton(actions, "Clear", on_clear, variant="secondary").pack(
            side="left", padx=(8, 0)
        )

    def _build_summary(self, master: tk.Misc) -> None:
        card = Card(master, padding=16)
        card.grid(row=0, column=0, sticky="ew")

        SectionHeader(card.body, "02", "Descriptor summary").pack(fill="x")

        self.session_row = KeyValueRow(card.body, "SESSION ID")
        self.runtime_row = KeyValueRow(card.body, "RUNTIME")
        self.host_row = KeyValueRow(card.body, "DISPLAY HOST")
        self.guest_row = KeyValueRow(card.body, "GUEST")

        for row in (self.session_row, self.runtime_row, self.host_row, self.guest_row):
            row.pack(fill="x", pady=4)

    def _build_validation(self, master: tk.Misc) -> None:
        card = Card(master, padding=16)
        card.grid(row=1, column=0, sticky="nsew", pady=(16, 0))

        SectionHeader(card.body, "03", "Validation").pack(fill="x")

        self.status_label = tk.Label(
            card.body,
            text="No descriptor loaded.",
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
            wraplength=280,
            height=2,
        )
        self.status_label.pack(fill="x", pady=(12, 0))

        self.code_label = tk.Label(
            card.body,
            text="",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().mono_font(8, "bold"),
            anchor="w",
        )
        self.code_label.pack(fill="x", pady=(6, 0))

        Divider(card.body).pack(fill="x", pady=10)

        for label, value in (
            ("SCHEMA", "tek.session.v0"),
            ("PROTOCOL", "tek/0"),
            ("TRANSPORT", "https only"),
            ("CREDENTIALS", "none in URL"),
            ("EXPIRY", "checked locally"),
        ):
            KeyValueRow(card.body, label, value).pack(fill="x", pady=2)

        tk.Label(
            card.body,
            text=(
                "Rejections report a stable code and never echo the URL or a "
                "credential."
            ),
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=280,
        ).pack(fill="x", pady=(12, 0))

    # -- state -----------------------------------------------------------

    def get_descriptor_text(self) -> str:
        return self.descriptor_input.get("1.0", "end")

    def set_descriptor_text(self, text: str) -> None:
        self.descriptor_input.delete("1.0", "end")
        self.descriptor_input.insert("1.0", text)

    def set_status(
        self, text: str, *, code: str | None = None, error: bool = False
    ) -> None:
        self.status_label.configure(text=text, fg=P["text"] if error else P["muted"])
        self.code_label.configure(text=code or "")

    def set_fields(
        self,
        *,
        session_id: str,
        runtime: str,
        host: str,
        guest: str,
    ) -> None:
        self.session_row.set(session_id)
        self.runtime_row.set(runtime)
        self.host_row.set(host)
        self.guest_row.set(guest)

    def clear_fields(self) -> None:
        for row in (self.session_row, self.runtime_row, self.host_row, self.guest_row):
            row.set("-")
