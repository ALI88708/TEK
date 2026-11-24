"""VM Configuration view — choose ISO / hardware, then generate the Kaggle notebook snippet.

The Controller does not start the VM itself: Kaggle runs it. This view produces the exact
code to paste into the TEK notebook on Kaggle (see tek_controller.snippet)."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from tek_controller import theme

P = theme.PALETTE


class VmConfigView(tk.Frame):
    """Let the user configure a guest VM before starting a session.

    Callback on_generated(config_dict, snippet) is called after a snippet is generated.
    config_dict keys:
      iso_type   : "url" | "path" | "alpine"
      iso_value  : URL string or file path (empty if iso_type="alpine")
      sha256     : optional SHA-256 hex
      display_name: human label
      disk_size_gb: float (0 = no disk)
      firmware   : "bios" | "uefi"
      machine    : "pc" | "q35"
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_generated: Callable[[dict, str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg=P["bg"])
        self._on_generated = on_generated
        self._on_cancel = on_cancel
        self._build()

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        # Header
        hdr = tk.Frame(self, bg=P["bg"])
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        tk.Label(hdr, text="CONFIGURE VIRTUAL MACHINE",
                 bg=P["bg"], fg=P["muted"],
                 font=theme.fonts().mono_font(8, "bold")).pack(anchor="w")
        tk.Label(hdr, text=(
            "Select an ISO to boot and configure the VM hardware. "
            "All computation runs on Kaggle — your machine is display-only."),
            bg=P["bg"], fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w", justify="left", wraplength=700).pack(anchor="w", pady=(4, 0))

        # --- ISO selection ---
        iso_card = self._card(1, "ISO Source")
        self._iso_type = tk.StringVar(value="alpine")
        opts = [
            ("alpine", "Alpine Linux (default test image — auto-downloaded)"),
            ("url",    "Download from URL"),
            ("path",   "Local file path (Kaggle dataset)"),
        ]
        for val, lbl in opts:
            tk.Radiobutton(
                iso_card, text=lbl, variable=self._iso_type, value=val,
                command=self._on_iso_type_change,
                bg=P["surface"], fg=P["text"], selectcolor=P["surface_alt"],
                activebackground=P["surface"],
                font=theme.fonts().ui_font(9), relief="flat",
            ).pack(anchor="w", pady=2)

        self._iso_lbl = tk.Label(iso_card, text="URL / Path:", bg=P["surface"],
                                  fg=P["muted"], font=theme.fonts().ui_font(8))
        self._iso_lbl.pack(anchor="w", pady=(10, 2))
        self._iso_val = tk.Entry(iso_card, bg=P["surface_alt"], fg=P["text"],
                                  insertbackground=P["text"],
                                  relief="flat", highlightthickness=1,
                                  highlightbackground=P["border"],
                                  font=theme.fonts().mono_font(9))
        self._iso_val.pack(fill="x", ipady=5)

        self._sha_lbl = tk.Label(iso_card, text="SHA-256 (optional):", bg=P["surface"],
                                  fg=P["muted"], font=theme.fonts().ui_font(8))
        self._sha_lbl.pack(anchor="w", pady=(8, 2))
        self._sha_val = tk.Entry(iso_card, bg=P["surface_alt"], fg=P["text"],
                                  insertbackground=P["text"],
                                  relief="flat", highlightthickness=1,
                                  highlightbackground=P["border"],
                                  font=theme.fonts().mono_font(8))
        self._sha_val.pack(fill="x", ipady=4)

        self._name_lbl = tk.Label(iso_card, text="Display name:", bg=P["surface"],
                                   fg=P["muted"], font=theme.fonts().ui_font(8))
        self._name_lbl.pack(anchor="w", pady=(8, 2))
        self._name_val = tk.Entry(iso_card, bg=P["surface_alt"], fg=P["text"],
                                   insertbackground=P["text"],
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=P["border"],
                                   font=theme.fonts().mono_font(9))
        self._name_val.pack(fill="x", ipady=5)
        self._name_val.insert(0, "Alpine Linux")

        # --- Hardware ---
        hw_card = self._card(2, "Hardware")
        for label, var_name, default, from_v, to_v, inc in [
            ("CPU cores (0 = auto)",  "_cpu_var",  0,  0, 64,  1),
            ("RAM MB (0 = auto)",     "_ram_var",  0,  0, 262144, 256),
            ("Disk GB (0 = no disk)",  "_disk_var", 0,  0, 500, 1),
        ]:
            row = tk.Frame(hw_card, bg=P["surface"])
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=P["surface"], fg=P["muted"],
                     font=theme.fonts().ui_font(8), width=28, anchor="w").pack(side="left")
            var = tk.IntVar(value=default)
            setattr(self, var_name, var)
            tk.Spinbox(row, from_=from_v, to=to_v, increment=inc,
                       textvariable=var,
                       bg=P["surface_alt"], fg=P["text"],
                       relief="flat", width=10,
                       font=theme.fonts().mono_font(9)).pack(side="left", ipady=4)

        # --- Firmware & Machine ---
        fw_card = self._card(3, "Firmware & Machine Type")

        fw_row = tk.Frame(fw_card, bg=P["surface"])
        fw_row.pack(fill="x", pady=4)
        tk.Label(fw_row, text="Firmware:", bg=P["surface"], fg=P["muted"],
                 font=theme.fonts().ui_font(8), width=18, anchor="w").pack(side="left")
        self._fw_var = tk.StringVar(value="bios")
        for val, lbl in [("bios", "BIOS (compatible)"), ("uefi", "UEFI (requires OVMF)")]:
            tk.Radiobutton(fw_row, text=lbl, variable=self._fw_var, value=val,
                           bg=P["surface"], fg=P["text"], selectcolor=P["surface_alt"],
                           activebackground=P["surface"],
                           font=theme.fonts().ui_font(8),
                           relief="flat").pack(side="left", padx=8)

        mt_row = tk.Frame(fw_card, bg=P["surface"])
        mt_row.pack(fill="x", pady=4)
        tk.Label(mt_row, text="Machine type:", bg=P["surface"], fg=P["muted"],
                 font=theme.fonts().ui_font(8), width=18, anchor="w").pack(side="left")
        self._mt_var = tk.StringVar(value="pc")
        for val, lbl in [("pc", "pc — i440FX (default)"), ("q35", "q35 — ICH9 (Windows)")]:
            tk.Radiobutton(mt_row, text=lbl, variable=self._mt_var, value=val,
                           bg=P["surface"], fg=P["text"], selectcolor=P["surface_alt"],
                           activebackground=P["surface"],
                           font=theme.fonts().ui_font(8),
                           relief="flat").pack(side="left", padx=8)

        # --- Disk notice ---
        notice_card = self._card(4, "⚠ Persistence Notice")
        tk.Label(notice_card,
                 text=(
                     "Kaggle sessions are TEMPORARY. Any virtual disk created here "
                     "will be LOST when the Kaggle kernel ends.\n"
                     "If you need to keep your data, export the disk before the session ends.\n"
                     "TEK does not currently implement automatic disk persistence."
                 ),
                 bg=P["surface"], fg=P.get("warning", "#e6a817"),
                 font=theme.fonts().ui_font(8),
                 anchor="w", justify="left", wraplength=700).pack(anchor="w")

        # --- Action buttons ---
        btn_row = tk.Frame(self, bg=P["bg"])
        btn_row.grid(row=5, column=0, sticky="ew", pady=(16, 0))

        self._status = tk.Label(btn_row, text="", bg=P["bg"], fg=P.get("danger", "#ff6b6b"),
                                font=theme.fonts().ui_font(9))
        self._status.pack(anchor="w", pady=(0, 8))

        btns = tk.Frame(btn_row, bg=P["bg"])
        btns.pack(anchor="w")
        tk.Button(btns, text="Generate Kaggle Snippet",
                  command=self._on_click_generate,
                  bg=P.get("accent", "#1a73e8"), fg="white",
                  relief="flat", padx=20, pady=8,
                  font=theme.fonts().ui_font(10, "bold")).pack(side="left")
        tk.Button(btns, text="Copy Snippet",
                  command=self._copy_snippet,
                  bg=P["surface_alt"], fg=P["text"],
                  relief="flat", padx=12, pady=8,
                  font=theme.fonts().ui_font(9)).pack(side="left", padx=(8, 0))
        tk.Button(btns, text="Cancel",
                  command=lambda: self._on_cancel and self._on_cancel(),
                  bg=P["surface_alt"], fg=P["text"],
                  relief="flat", padx=12, pady=8,
                  font=theme.fonts().ui_font(9)).pack(side="left", padx=(8, 0))

        tk.Label(btn_row, text=(
            "TEK does not launch Kaggle notebooks for you. Paste this snippet into the last cell of "
            "kaggle/tek_runtime.ipynb (after setting TEK_SESSION_SECRET) and run it on Kaggle. "
            "CPU/RAM/disk are checked against the real Kaggle limits when it runs."),
            bg=P["bg"], fg=P["muted"], font=theme.fonts().ui_font(8),
            justify="left", wraplength=700, anchor="w").pack(anchor="w", pady=(10, 4))
        self._snippet = tk.Text(btn_row, height=9, bg=P["surface_alt"], fg=P["text"],
                                font=theme.fonts().mono_font(9), relief="flat", wrap="none",
                                state="disabled")
        self._snippet.pack(fill="x", pady=(0, 4))

        self._on_iso_type_change()

    # ------------------------------------------------------------------ #

    def _card(self, row: int, title: str) -> tk.Frame:
        card = tk.Frame(self, bg=P["surface"],
                        highlightthickness=1, highlightbackground=P["border"])
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        tk.Label(card, text=title, bg=P["surface"], fg=P["text"],
                 font=theme.fonts().ui_font(10, "bold"),
                 padx=16, pady=10).pack(anchor="w")
        body = tk.Frame(card, bg=P["surface"])
        body.pack(fill="x", padx=16, pady=(0, 12))
        return body

    def _on_iso_type_change(self) -> None:
        iso_type = self._iso_type.get()
        url_visible = iso_type != "alpine"
        state = "normal" if url_visible else "disabled"
        self._iso_val.configure(state=state)
        self._sha_val.configure(state=state)
        label = "URL:" if iso_type == "url" else "File path:"
        self._iso_lbl.configure(text=label if url_visible else "")
        # Update default name
        if iso_type == "alpine":
            self._name_val.delete(0, "end")
            self._name_val.insert(0, "Alpine Linux")

    def _collect(self) -> dict:
        return {
            "iso_type":     self._iso_type.get(),
            "iso_value":    self._iso_val.get().strip(),
            "sha256":       self._sha_val.get().strip(),
            "display_name": self._name_val.get().strip() or "Guest OS",
            "disk_size_gb": float(self._disk_var.get()),
            "vcpu":         int(self._cpu_var.get()) or None,
            "ram_mb":       int(self._ram_var.get()) or None,
            "firmware":     self._fw_var.get(),
            "machine":      self._mt_var.get(),
        }

    def _on_click_generate(self) -> None:
        from tek_controller.snippet import build_notebook_snippet
        config = self._collect()
        try:
            snippet = build_notebook_snippet(config)
        except (ValueError, tk.TclError) as exc:
            self._status.configure(text=str(exc))
            return
        self._status.configure(text="")
        self._snippet.configure(state="normal")
        self._snippet.delete("1.0", "end")
        self._snippet.insert("1.0", snippet)
        self._snippet.configure(state="disabled")
        if self._on_generated:
            self._on_generated(config, snippet)

    def _copy_snippet(self) -> None:
        text = self._snippet.get("1.0", "end").strip()
        if not text:
            self._status.configure(text="Generate the snippet first.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status.configure(text="")

    def set_error(self, msg: str) -> None:
        self._status.configure(text=msg)
