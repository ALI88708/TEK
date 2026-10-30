"""Reusable monochrome widgets."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any, ClassVar

from tek_controller import theme
from tek_controller.session import STATE_ORDER, SessionState

P = theme.PALETTE


def _hover(widget: tk.Button, normal: str, hover: str) -> None:
    def enter(_event: tk.Event) -> None:
        if str(widget.cget("state")) != "disabled":
            widget.configure(bg=hover)

    def leave(_event: tk.Event) -> None:
        if str(widget.cget("state")) != "disabled":
            widget.configure(bg=normal)

    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)


class Card(tk.Frame):
    """A bordered surface panel."""

    def __init__(self, master: tk.Misc, *, padding: int = 18, **kwargs: Any) -> None:
        super().__init__(
            master,
            bg=P["surface"],
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["border"],
            **kwargs,
        )
        self.body = tk.Frame(self, bg=P["surface"])
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class Divider(tk.Frame):
    def __init__(self, master: tk.Misc, *, colour: str | None = None) -> None:
        super().__init__(master, bg=colour or P["border"], height=1)


class SectionHeader(tk.Frame):
    """`01 / SESSION` plus a rule that fills the remaining width."""

    def __init__(self, master: tk.Misc, index: str, title: str) -> None:
        super().__init__(master, bg=master.cget("bg"))
        fonts = theme.fonts()

        tk.Label(
            self,
            text=f"{index} / {title.upper()}",
            bg=self.cget("bg"),
            fg=P["dim"],
            font=fonts.mono_font(8, "bold"),
        ).pack(side="left")

        tk.Frame(self, bg=P["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(12, 0)
        )


class ActionButton(tk.Button):
    """Flat button in three weights: primary (inverted), secondary, ghost."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], object],
        *,
        variant: str = "primary",
        **kwargs: Any,
    ) -> None:
        fonts = theme.fonts()
        options: dict[str, Any]

        if variant == "primary":
            options = {
                "bg": P["text"],
                "fg": P["inverse"],
                "activebackground": "#E2E2E7",
                "activeforeground": P["inverse"],
                "highlightthickness": 0,
                "hover": "#E2E2E7",
            }
        elif variant == "secondary":
            options = {
                "bg": P["surface_alt"],
                "fg": P["text"],
                "activebackground": P["hover"],
                "activeforeground": P["text"],
                "highlightthickness": 1,
                "highlightbackground": P["border_strong"],
                "highlightcolor": P["border_strong"],
                "hover": P["hover"],
            }
        else:
            options = {
                "bg": P["surface"],
                "fg": P["muted"],
                "activebackground": P["surface"],
                "activeforeground": P["text"],
                "highlightthickness": 0,
                "hover": P["surface"],
            }

        hover = options.pop("hover")
        super().__init__(
            master,
            text=text,
            command=command,
            bd=0,
            relief="flat",
            cursor="hand2",
            font=fonts.ui_font(9, "bold"),
            padx=16,
            pady=9,
            disabledforeground=P["dim"],
            **options,
            **kwargs,
        )
        _hover(self, options["bg"], hover)


class StatusPill(tk.Frame):
    """Current session state as an outlined chip."""

    _STYLES: ClassVar[dict[SessionState, tuple[str, str, str]]] = {
        SessionState.IDLE: (P["surface_alt"], P["muted"], P["border"]),
        SessionState.PREPARING: (P["surface_hi"], P["text"], P["border_strong"]),
        SessionState.CONNECTING: (P["surface_hi"], P["text"], P["border_strong"]),
        SessionState.RUNNING: (P["text"], P["inverse"], P["text"]),
        SessionState.STOPPING: (P["surface_alt"], P["muted"], P["border_strong"]),
        SessionState.FAILED: (P["surface"], P["text"], P["text"]),
    }

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(
            master,
            bg=P["surface_alt"],
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        self.label = tk.Label(
            self,
            text="IDLE",
            bg=P["surface_alt"],
            fg=P["muted"],
            font=theme.fonts().mono_font(8, "bold"),
            padx=10,
            pady=4,
        )
        self.label.pack()

    def set_state(self, state: SessionState) -> None:
        background, foreground, border = self._STYLES[state]
        self.configure(bg=background, highlightbackground=border, highlightcolor=border)
        self.label.configure(
            text=f"{state.value.upper()}", bg=background, fg=foreground
        )


class StageRail(tk.Canvas):
    """Six-segment rail showing where the session sits in its lifecycle."""

    def __init__(self, master: tk.Misc, *, height: int = 10) -> None:
        super().__init__(
            master,
            height=height,
            bg=P["surface"],
            highlightthickness=0,
            bd=0,
        )
        self._index = 0
        self.bind("<Configure>", lambda _event: self._draw())

    def set_state(self, state: SessionState) -> None:
        self._index = STATE_ORDER.index(state)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            return

        gap = 4
        count = len(STATE_ORDER)
        segment = (width - gap * (count - 1)) / count

        for position in range(count):
            x0 = position * (segment + gap)
            x1 = x0 + segment
            if position < self._index:
                fill = P["border_strong"]
            elif position == self._index:
                fill = P["text"]
            else:
                fill = P["border"]
            self.create_rectangle(x0, 0, x1, 6, fill=fill, outline="")


class KeyValueRow(tk.Frame):
    def __init__(self, master: tk.Misc, label: str, value: str = "-") -> None:
        super().__init__(master, bg=master.cget("bg"))
        fonts = theme.fonts()

        tk.Label(
            self,
            text=label,
            bg=self.cget("bg"),
            fg=P["dim"],
            font=fonts.mono_font(8),
            anchor="w",
        ).pack(side="left")

        self.value = tk.Label(
            self,
            text=value,
            bg=self.cget("bg"),
            fg=P["text"],
            font=fonts.mono_font(8),
            anchor="e",
        )
        self.value.pack(side="right")

    def set(self, value: str) -> None:
        self.value.configure(text=value)


class LabeledEntry(tk.Frame):
    def __init__(self, master: tk.Misc, label: str, *, hint: str = "") -> None:
        super().__init__(master, bg=master.cget("bg"))
        fonts = theme.fonts()

        tk.Label(
            self,
            text=label.upper(),
            bg=self.cget("bg"),
            fg=P["dim"],
            font=fonts.mono_font(8, "bold"),
            anchor="w",
        ).pack(fill="x")

        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self,
            textvariable=self.var,
            bg=P["surface_alt"],
            fg=P["text"],
            insertbackground=P["text"],
            disabledbackground=P["surface_alt"],
            disabledforeground=P["dim"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["border_strong"],
            font=fonts.mono_font(9),
        )
        self.entry.pack(fill="x", ipady=7, pady=(6, 0))

        if hint:
            tk.Label(
                self,
                text=hint,
                bg=self.cget("bg"),
                fg=P["dim"],
                font=fonts.ui_font(8),
                anchor="w",
            ).pack(fill="x", pady=(5, 0))


class CheckRow(tk.Frame):
    def __init__(
        self, master: tk.Misc, label: str, *, hint: str = "", wrap: int = 340
    ) -> None:
        super().__init__(master, bg=master.cget("bg"))
        fonts = theme.fonts()

        self.var = tk.BooleanVar(value=False)
        self.button = tk.Checkbutton(
            self,
            text=label,
            variable=self.var,
            bg=self.cget("bg"),
            fg=P["text"],
            activebackground=self.cget("bg"),
            activeforeground=P["text"],
            selectcolor=P["surface_alt"],
            font=fonts.ui_font(9),
            bd=0,
            highlightthickness=0,
            anchor="w",
            cursor="hand2",
        )
        self.button.pack(anchor="w")

        if hint:
            tk.Label(
                self,
                text=hint,
                bg=self.cget("bg"),
                fg=P["dim"],
                font=fonts.ui_font(8),
                anchor="w",
                justify="left",
                wraplength=wrap,
            ).pack(anchor="w", padx=(22, 0), pady=(2, 0))


class SegmentedControl(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        choices: Sequence[int],
        *,
        suffix: str = "%",
    ) -> None:
        super().__init__(
            master,
            bg=P["surface_alt"],
            bd=0,
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        fonts = theme.fonts()
        self.var = tk.IntVar(value=choices[1] if len(choices) > 1 else choices[0])
        self._cells: dict[int, tk.Label] = {}

        for choice in choices:
            cell = tk.Label(
                self,
                text=f"{choice}{suffix}",
                bg=P["surface_alt"],
                fg=P["muted"],
                font=fonts.mono_font(8, "bold"),
                padx=9,
                pady=7,
                cursor="hand2",
            )
            cell.pack(side="left")

            def _select(_event: tk.Event, value: int = choice) -> None:
                self.set(value)

            cell.bind("<Button-1>", _select)
            self._cells[choice] = cell

        self.var.trace_add("write", lambda *_args: self._paint())
        self._paint()

    def get(self) -> int:
        return self.var.get()

    def set(self, value: int) -> None:
        self.var.set(value)
        self._paint()

    def _paint(self) -> None:
        current = self.var.get()
        for value, cell in self._cells.items():
            if value == current:
                cell.configure(bg=P["text"], fg=P["inverse"])
            else:
                cell.configure(bg=P["surface_alt"], fg=P["muted"])
