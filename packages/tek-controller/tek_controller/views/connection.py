"""Connection view: fetch descriptor from a live runtime, or paste manually."""
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
        on_generate_secret: Callable[[], None] | None = None,
        on_fetch: Callable[[], None] | None = None,
        on_open_display: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg=P["bg"])
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0, minsize=340)
        self.rowconfigure(0, weight=1)

        self._on_generate_secret = on_generate_secret
        self._on_fetch = on_fetch
        self._on_open_display = on_open_display
        self._stored_secret: bytes | None = None

        self._build_input(self, on_connect, on_clear)

        right = tk.Frame(self, bg=P["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_summary(right)
        self._build_validation(right)

    # ------------------------------------------------------------------ #

    def _build_input(
        self,
        master: tk.Misc,
        on_connect: Callable[[], object],
        on_clear: Callable[[], None],
    ) -> None:
        left = tk.Frame(master, bg=P["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        # ---- Section 00: connect to runtime ----------------------------
        setup_card = Card(left, padding=18)
        setup_card.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        SectionHeader(setup_card.body, "00", "Connect to runtime").pack(fill="x")

        tk.Label(
            setup_card.body,
            text=(
                "Generate a session secret, paste it into TEK_SESSION_SECRET "
                "in your Kaggle notebook, run the notebook, then enter the "
                "tunnel hostname it prints and click Fetch."
            ),
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x", pady=(10, 0))

        # Secret row
        secret_row = tk.Frame(setup_card.body, bg=P["surface"])
        secret_row.pack(fill="x", pady=(14, 0))

        self.secret_display = tk.Entry(
            secret_row,
            bg=P["surface_alt"],
            fg=P["text"],
            insertbackground=P["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=P["border"],
            font=theme.fonts().mono_font(8),
            show="\u2022",
            width=38,
        )
        self.secret_display.pack(side="left", ipady=5, padx=(0, 8))
        self.secret_display.config(state="readonly")

        self._copy_btn = ActionButton(
            secret_row, "Copy", self._copy_secret, variant="secondary"
        )
        self._copy_btn.pack(side="left", padx=(0, 8))

        self._reveal_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            secret_row,
            text="Show",
            variable=self._reveal_var,
            command=self._toggle_reveal,
            bg=P["surface"],
            fg=P["muted"],
            selectcolor=P["surface_alt"],
            activebackground=P["surface"],
            font=theme.fonts().ui_font(8),
            relief="flat",
            bd=0,
        ).pack(side="left")

        ActionButton(
            setup_card.body,
            "Generate Secret",
            lambda: self._on_generate_secret and self._on_generate_secret(),
            variant="secondary",
        ).pack(anchor="w", pady=(10, 0))

        # Pair nonce display
        tk.Label(
            setup_card.body,
            text="Expected pair code (verify against notebook output):",
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(8),
            anchor="w",
        ).pack(fill="x", pady=(14, 2))

        self.pair_label = tk.Label(
            setup_card.body,
            text="\u2014\u2014",
            bg=P["surface"],
            fg=P["text"],
            font=theme.fonts().mono_font(11, "bold"),
            anchor="w",
        )
        self.pair_label.pack(fill="x")

        Divider(setup_card.body).pack(fill="x", pady=14)

        # Host input
        host_row = tk.Frame(setup_card.body, bg=P["surface"])
        host_row.pack(fill="x")

        tk.Label(
            host_row,
            text="Tunnel host",
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(8),
            width=12,
            anchor="w",
        ).pack(side="left")

        self.host_entry = tk.Entry(
            host_row,
            bg=P["surface_alt"],
            fg=P["text"],
            insertbackground=P["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["border_strong"],
            font=theme.fonts().mono_font(9),
        )
        self.host_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.host_entry.insert(0, "abc-def-123.trycloudflare.com")

        # Fetch + Open display buttons
        fetch_row = tk.Frame(setup_card.body, bg=P["surface"])
        fetch_row.pack(fill="x", pady=(12, 0))

        ActionButton(
            fetch_row,
            "Fetch & Connect",
            lambda: self._on_fetch and self._on_fetch(),
            variant="primary",
        ).pack(side="left")

        self.open_btn = ActionButton(
            fetch_row,
            "Open Display",
            lambda: self._on_open_display and self._on_open_display(),
            variant="secondary",
        )
        self.open_btn.pack(side="left", padx=(8, 0))
        self.open_btn.set_enabled(False)

        # ---- Section 01: paste descriptor (manual fallback) ------------
        paste_card = Card(left, padding=18)
        paste_card.grid(row=1, column=0, sticky="nsew")

        SectionHeader(paste_card.body, "01", "Paste descriptor (fallback)").pack(
            fill="x"
        )

        tk.Label(
            paste_card.body,
            text=(
                "Paste the descriptor JSON from GET /tek/descriptor "
                "if Fetch is unavailable."
            ),
            bg=P["surface"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x", pady=(10, 0))

        self.descriptor_input = tk.Text(
            paste_card.body,
            height=7,
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
        self.descriptor_input.pack(fill="both", expand=True, pady=(10, 0))

        tk.Label(
            paste_card.body,
            text="Descriptor only. Do not paste a secret or token here.",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x", pady=(8, 0))

        actions = tk.Frame(paste_card.body, bg=P["surface"])
        actions.pack(fill="x", pady=(12, 0))

        ActionButton(actions, "Validate", on_connect, variant="primary").pack(
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
            text="Rejections report a stable code and never echo a credential.",
            bg=P["surface"],
            fg=P["dim"],
            font=theme.fonts().ui_font(8),
            anchor="w",
            justify="left",
            wraplength=280,
        ).pack(fill="x", pady=(12, 0))

    # ------------------------------------------------------------------ #
    # Secret management (in-memory only)                                   #
    # ------------------------------------------------------------------ #

    def set_secret(self, secret: bytes) -> None:
        from tek_controller.crypto import pairing_nonce, secret_to_str

        self._stored_secret = secret
        encoded = secret_to_str(secret)
        self.secret_display.config(state="normal")
        self.secret_display.delete(0, "end")
        self.secret_display.insert(0, encoded)
        self.secret_display.config(state="readonly", show="\u2022")
        self._reveal_var.set(False)
        self.pair_label.configure(text=pairing_nonce(secret))

    def get_secret(self) -> bytes | None:
        return self._stored_secret

    def get_host(self) -> str:
        return self.host_entry.get().strip()

    def _copy_secret(self) -> None:
        if not self._stored_secret:
            return
        from tek_controller.crypto import secret_to_str
        self.secret_display.clipboard_clear()
        self.secret_display.clipboard_append(secret_to_str(self._stored_secret))

    def _toggle_reveal(self) -> None:
        self.secret_display.config(
            show="" if self._reveal_var.get() else "\u2022"
        )

    # ------------------------------------------------------------------ #
    # State accessors (kept API-compatible with the original view)         #
    # ------------------------------------------------------------------ #

    def get_descriptor_text(self) -> str:
        return self.descriptor_input.get("1.0", "end")

    def set_descriptor_text(self, text: str) -> None:
        self.descriptor_input.delete("1.0", "end")
        self.descriptor_input.insert("1.0", text)

    def set_status(
        self, text: str, *, code: str | None = None, error: bool = False
    ) -> None:
        self.status_label.configure(
            text=text,
            fg=P.get("danger", "#ff6b6b") if error else P["muted"],
        )
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

    def set_open_display_enabled(self, enabled: bool) -> None:
        self.open_btn.set_enabled(enabled)
