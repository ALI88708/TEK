"""Left navigation rail."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from functools import partial

from tek_controller import PROTOCOL_VERSION, __version__, theme

P = theme.PALETTE


def _bind_tree(widget: tk.Misc, sequence: str, handler: Callable[[tk.Event], None]) -> None:
    widget.bind(sequence, handler)
    for child in widget.winfo_children():
        _bind_tree(child, sequence, handler)


class NavItem(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        index: str,
        label: str,
        command: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=P["panel"], cursor="hand2")
        fonts = theme.fonts()

        self.indicator = tk.Frame(self, width=2, bg=P["panel"])
        self.indicator.pack(side="left", fill="y")

        self.content = tk.Frame(self, bg=P["panel"])
        self.content.pack(side="left", fill="both", expand=True, padx=14, pady=9)

        self.index_label = tk.Label(
            self.content,
            text=index,
            bg=P["panel"],
            fg=P["dim"],
            font=fonts.mono_font(8),
            width=3,
            anchor="w",
        )
        self.index_label.pack(side="left")

        self.text_label = tk.Label(
            self.content,
            text=label,
            bg=P["panel"],
            fg=P["muted"],
            font=fonts.ui_font(10),
            anchor="w",
        )
        self.text_label.pack(side="left")

        self._active = False
        _bind_tree(self, "<Button-1>", lambda _event: command())
        _bind_tree(self, "<Enter>", lambda _event: self._paint(hover=True))
        _bind_tree(self, "<Leave>", lambda _event: self._paint(hover=False))

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint(hover=False)

    def _paint(self, *, hover: bool) -> None:
        if self._active:
            background = P["surface_alt"]
            foreground = P["text"]
            indicator = P["text"]
        elif hover:
            background = P["hover"]
            foreground = P["text"]
            indicator = P["border_strong"]
        else:
            background = P["panel"]
            foreground = P["muted"]
            indicator = P["panel"]

        self.indicator.configure(bg=indicator)
        for widget in (self, self.content):
            widget.configure(bg=background)
        for label_widget in (self.index_label, self.text_label):
            label_widget.configure(
                bg=background,
                fg=foreground if label_widget is self.text_label else P["dim"],
            )


class Sidebar(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        items: Sequence[tuple[str, str, str]],
        on_select: Callable[[str], None],
    ) -> None:
        super().__init__(master, bg=P["panel"], width=236)
        self.pack_propagate(False)
        fonts = theme.fonts()

        tk.Frame(self, bg=P["border"], width=1).pack(side="right", fill="y")

        heading = tk.Frame(self, bg=P["panel"])
        heading.pack(fill="x", padx=16, pady=(20, 10))
        tk.Label(
            heading,
            text="NAVIGATION",
            bg=P["panel"],
            fg=P["dim"],
            font=fonts.mono_font(8, "bold"),
        ).pack(anchor="w")

        self._items: dict[str, NavItem] = {}
        for index, key, label in items:
            item = NavItem(self, index, label, partial(on_select, key))
            item.pack(fill="x")
            self._items[key] = item

        footer = tk.Frame(self, bg=P["panel"])
        footer.pack(side="bottom", fill="x", padx=16, pady=18)

        tk.Frame(footer, bg=P["border"], height=1).pack(fill="x", pady=(0, 12))
        for line in (
            "PROTOTYPE BUILD",
            f"Controller {__version__}",
            f"Protocol {PROTOCOL_VERSION}",
        ):
            tk.Label(
                footer,
                text=line,
                bg=P["panel"],
                fg=P["dim"],
                font=fonts.mono_font(8),
                anchor="w",
            ).pack(fill="x")

    def set_active(self, key: str) -> None:
        for name, item in self._items.items():
            item.set_active(name == key)
