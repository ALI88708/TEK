"""Application shell for the TEK Controller prototype.

The window, navigation, and local state are real. The runtime transport is not:
every action that would need a live TEK Runtime says so instead of pretending.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from urllib.parse import urlsplit

from tek_controller import theme
from tek_controller.descriptor import (
    DescriptorError,
    SessionDescriptor,
    parse_descriptor,
)
from tek_controller.session import SessionModel, SessionState
from tek_controller.settings import (
    TIMEOUT_MAX_S,
    TIMEOUT_MIN_S,
    Settings,
    default_settings_path,
    load_settings,
    save_settings,
)
from tek_controller.views.connection import ConnectionView
from tek_controller.views.dashboard import DashboardView
from tek_controller.views.settings import SettingsView
from tek_controller.widgets.primitives import StatusPill
from tek_controller.widgets.sidebar import Sidebar

P = theme.PALETTE

VIEW_META: dict[str, tuple[str, str]] = {
    "dashboard": (
        "Session dashboard",
        "Create a temporary environment and watch the runtime link.",
    ),
    "connection": (
        "Connection",
        "Load and validate a session descriptor served by the TEK Runtime.",
    ),
    "settings": (
        "Settings",
        "Local controller preferences. Nothing here leaves this machine.",
    ),
}


class TekControllerApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        settings_path: Path | str | None = None,
        create_delay_ms: int = 650,
    ) -> None:
        self.root = root
        theme.init_fonts(root)

        self.settings_path = (
            Path(settings_path) if settings_path is not None else default_settings_path()
        )
        self.settings = load_settings(self.settings_path)
        self.create_delay_ms = create_delay_ms

        self.session = SessionModel()
        self.descriptor: SessionDescriptor | None = None
        self.connection_error_code: str | None = None
        self.current_view = "dashboard"
        self._create_job: str | None = None

        self._configure_window()
        self._build_header()
        self._build_body()
        self._build_views()

        self.show_view("dashboard")
        self._apply_settings(self.settings)
        self._log_startup()

    # -- window chrome ---------------------------------------------------

    def _configure_window(self) -> None:
        self.root.title("TEK Controller - Temporary Environment on Kaggle")
        self.root.configure(bg=P["bg"])
        self.root.minsize(1120, 720)

        width, height = 1280, 840
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(width, max(980, screen_w - 120))
        height = min(height, max(700, screen_h - 140))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Control-Key-1>", lambda _event: self.show_view("dashboard"))
        self.root.bind("<Control-Key-2>", lambda _event: self.show_view("connection"))
        self.root.bind("<Control-Key-3>", lambda _event: self.show_view("settings"))
        self._set_icon()

    def _set_icon(self) -> None:
        icon = tk.PhotoImage(width=32, height=32)
        icon.put(P["panel"], to=(0, 0, 32, 32))
        for row in range(2):
            for column in range(2):
                x0 = 4 + column * 13
                y0 = 4 + row * 13
                fill = P["text"] if (row, column) == (0, 0) else P["muted"]
                icon.put(fill, to=(x0, y0, x0 + 11, y0 + 11))
        try:
            self.root.iconphoto(True, icon)
        except tk.TclError:
            return
        self._icon = icon

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=P["panel"], height=60)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Frame(header, bg=P["border"], height=1).pack(side="bottom", fill="x")

        brand = tk.Frame(header, bg=P["panel"])
        brand.pack(side="left", padx=(20, 0))

        mark = tk.Canvas(
            brand, width=24, height=24, bg=P["panel"], highlightthickness=0, bd=0
        )
        mark.pack(side="left")
        for row in range(2):
            for column in range(2):
                x0 = column * 13
                y0 = row * 13
                fill = P["text"] if (row, column) == (0, 0) else P["border_strong"]
                mark.create_rectangle(x0, y0, x0 + 11, y0 + 11, fill=fill, outline="")

        wordmark = tk.Frame(brand, bg=P["panel"])
        wordmark.pack(side="left", padx=(10, 0))

        self.brand_label = tk.Label(
            wordmark,
            text="TEK",
            bg=P["panel"],
            fg=P["text"],
            font=theme.fonts().ui_font(14, "bold"),
            anchor="w",
        )
        self.brand_label.pack(anchor="w")

        tk.Label(
            wordmark,
            text="CONTROLLER",
            bg=P["panel"],
            fg=P["dim"],
            font=theme.fonts().mono_font(7, "bold"),
            anchor="w",
        ).pack(anchor="w")

        tk.Frame(header, bg=P["border"], width=1, height=26).pack(
            side="left", padx=18
        )

        tk.Label(
            header,
            text="TEMPORARY ENVIRONMENT ON KAGGLE",
            bg=P["panel"],
            fg=P["muted"],
            font=theme.fonts().mono_font(8),
        ).pack(side="left")

        self.status_pill = StatusPill(header)
        self.status_pill.pack(side="right", padx=(0, 20))
        self.status_pill.set_state(self.session.state)

        self._chip(header, "tek/0").pack(side="right", padx=(0, 8))
        self._chip(header, "PROTOTYPE BUILD").pack(side="right", padx=(0, 8))

    def _chip(self, master: tk.Misc, text: str) -> tk.Frame:
        frame = tk.Frame(
            master,
            bg=P["surface_alt"],
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        tk.Label(
            frame,
            text=text,
            bg=P["surface_alt"],
            fg=P["muted"],
            font=theme.fonts().mono_font(8, "bold"),
            padx=9,
            pady=4,
        ).pack()
        return frame

    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=P["bg"])
        body.pack(fill="both", expand=True)

        self.sidebar = Sidebar(
            body,
            (
                ("01", "dashboard", "Session"),
                ("02", "connection", "Connection"),
                ("03", "settings", "Settings"),
            ),
            self.show_view,
        )
        self.sidebar.pack(side="left", fill="y")

        main = tk.Frame(body, bg=P["bg"])
        main.pack(side="left", fill="both", expand=True)

        heading = tk.Frame(main, bg=P["bg"])
        heading.pack(fill="x", padx=28, pady=(18, 12))

        tk.Label(
            heading,
            text="TEK / CONTROLLER",
            bg=P["bg"],
            fg=P["dim"],
            font=theme.fonts().mono_font(8, "bold"),
            anchor="w",
        ).pack(fill="x")

        self.view_title = tk.Label(
            heading,
            text="",
            bg=P["bg"],
            fg=P["text"],
            font=theme.fonts().ui_font(19, "bold"),
            anchor="w",
        )
        self.view_title.pack(fill="x", pady=(4, 2))

        self.view_subtitle = tk.Label(
            heading,
            text="",
            bg=P["bg"],
            fg=P["muted"],
            font=theme.fonts().ui_font(9),
            anchor="w",
            justify="left",
        )
        self.view_subtitle.pack(fill="x")

        self.container = tk.Frame(main, bg=P["bg"])
        self.container.pack(fill="both", expand=True, padx=28, pady=(0, 18))
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

    def _build_views(self) -> None:
        self.dashboard = DashboardView(
            self.container,
            on_create=self.create_session,
            on_open_connection=lambda: self.show_view("connection"),
        )
        self.connection_view = ConnectionView(
            self.container,
            on_connect=self.connect,
            on_clear=self.clear_descriptor,
        )
        self.settings_view = SettingsView(
            self.container,
            settings_path=self.settings_path,
            on_save=self.save_preferences,
            on_restore=self.restore_default_preferences,
        )

        self.views: dict[str, tk.Frame] = {
            "dashboard": self.dashboard,
            "connection": self.connection_view,
            "settings": self.settings_view,
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew")
            view.grid_remove()

        self.settings_view.load(self.settings)

        # Flat aliases used by the smoke tests and by small callers.
        self.notice_label = self.dashboard.notice_label
        self.session_id_label = self.dashboard.session_id_label.value
        self.event_log = self.dashboard.event_log
        self.connection_status_label = self.connection_view.status_label
        self.descriptor_input = self.connection_view.descriptor_input

    # -- navigation ------------------------------------------------------

    def show_view(self, key: str) -> None:
        view = self.views.get(key)
        if view is None:
            return

        for other in self.views.values():
            other.grid_remove()

        view.grid()
        self.current_view = key
        self.sidebar.set_active(key)

        title, subtitle = VIEW_META[key]
        self.view_title.configure(text=title)
        self.view_subtitle.configure(text=subtitle)

        if key == "connection":
            self.root.after_idle(self.descriptor_input.focus_set)

    # -- session actions -------------------------------------------------

    def create_session(self) -> None:
        if self.session.state is SessionState.FAILED:
            self.session.transition(SessionState.IDLE, "reset after failure")

        if self.session.state is not SessionState.IDLE:
            self.dashboard.set_notice("A session is already in progress.")
            return

        self.session.transition(SessionState.PREPARING, "create session requested")
        self._reset_connection_view()
        self.dashboard.set_session_id("-")
        self.dashboard.set_state(self.session.state)
        self.dashboard.set_runtime("REQUESTED")
        self.dashboard.set_runtime_status("PREPARING")
        self.dashboard.set_notice(
            "Preparing the session. No runtime link is established yet."
        )
        self.dashboard.log("Create session requested.")
        self._sync_status()

        self._create_job = self.root.after(
            self.create_delay_ms, self._abort_unimplemented_create
        )

    def _abort_unimplemented_create(self) -> None:
        self._create_job = None
        if self.session.state is not SessionState.PREPARING:
            return

        self.session.transition(
            SessionState.IDLE, "runtime integration unavailable in this build"
        )
        self.dashboard.set_state(self.session.state)
        self.dashboard.set_runtime("NOT CONNECTED")
        self.dashboard.set_runtime_status("NOT CONNECTED")
        self.dashboard.set_notice(
            "Runtime integration is not implemented in this build.\n"
            "No virtual machine was created and no Kaggle notebook was started."
        )
        self.dashboard.log("Runtime integration not implemented; no VM created.")
        self._sync_status()

    # -- connection actions ----------------------------------------------

    def connect(self) -> bool:
        raw = self.connection_view.get_descriptor_text()

        try:
            parsed = parse_descriptor(raw, check_expiry=self.settings.verify_expiry)
        except DescriptorError as error:
            self._reject_descriptor(error)
            return False

        self.connection_error_code = None
        self.descriptor = parsed

        host = urlsplit(parsed.display.url).hostname or "-"
        width, height = parsed.display.geometry
        self.connection_view.set_fields(
            session_id=parsed.session_id,
            runtime=parsed.runtime_version,
            host=f"{host} / {width}x{height}",
            guest=f"{parsed.guest.os} / {parsed.guest.state}",
        )
        self.connection_view.set_status(
            "Descriptor valid. Runtime integration is not implemented, so no "
            "viewer was attached.",
            code="VALID",
        )

        self.session_id_label.configure(text=parsed.session_id)
        self.dashboard.set_notice(
            "Descriptor loaded. Runtime integration is not implemented, so no "
            "viewer is attached."
        )
        self.dashboard.log(
            f"Descriptor accepted: {parsed.protocol}, session {parsed.session_id}, "
            f"guest {parsed.guest.os}."
        )
        self.dashboard.log(
            "Runtime integration not implemented; no connection attempted."
        )
        return True

    def _reject_descriptor(self, error: DescriptorError) -> None:
        self.connection_error_code = error.code
        self.descriptor = None
        self.connection_view.clear_fields()
        self.connection_view.set_status(error.message, code=error.code, error=True)
        self.dashboard.log(f"Descriptor rejected: {error.code}.")

    def set_descriptor_text(self, text: str) -> None:
        self.connection_view.set_descriptor_text(text)

    def clear_descriptor(self) -> None:
        self._reset_connection_view()
        self.dashboard.log("Descriptor cleared.")

    def _reset_connection_view(self) -> None:
        self.connection_view.set_descriptor_text("")
        self.connection_view.clear_fields()
        self.connection_view.set_status("No descriptor loaded.")
        self.connection_error_code = None
        self.descriptor = None

    # -- preferences -----------------------------------------------------

    def _settings_from_form(self) -> Settings | None:
        timeout = self.settings_view.timeout_value()
        if timeout is None:
            self.settings_view.set_status(
                f"Connection timeout must be a whole number between "
                f"{TIMEOUT_MIN_S} and {TIMEOUT_MAX_S} seconds.",
                error=True,
            )
            return None

        return Settings(
            fit_display=bool(self.settings_view.fit_var.get()),
            scale_percent=int(self.settings_view.scale_var.get()),
            show_grid=bool(self.settings_view.grid_var.get()),
            connect_timeout_s=timeout,
            verify_expiry=bool(self.settings_view.verify_var.get()),
            remembered_host=self.settings.remembered_host,
        )

    def save_preferences(self) -> bool:
        updated = self._settings_from_form()
        if updated is None:
            return False

        try:
            save_settings(updated, self.settings_path)
        except OSError:
            self.settings_view.set_status(
                "Preferences could not be saved. The settings file is not writable.",
                error=True,
            )
            self.dashboard.log("Preferences could not be saved.")
            return False

        self.settings = updated
        self._apply_settings(updated)
        self.settings_view.set_status("Preferences saved.")
        self.dashboard.log("Preferences saved.")
        return True

    def restore_default_preferences(self) -> None:
        self.settings_view.load(Settings())
        self.settings_view.set_status(
            "Defaults restored in the form. Save Preferences to apply."
        )

    def _apply_settings(self, settings: Settings) -> None:
        self.dashboard.display.set_grid_visible(settings.show_grid)
        self.dashboard.display.set_scale(settings.scale_percent)
        self.dashboard.display.set_fit(settings.fit_display)

    # -- misc ------------------------------------------------------------

    def _sync_status(self) -> None:
        self.status_pill.set_state(self.session.state)

    def _log_startup(self) -> None:
        self.dashboard.log("Controller started. No runtime connection.")
        self.dashboard.log("Runtime transport is not implemented in this build.")

    def close(self) -> None:
        if self._create_job is not None:
            self.root.after_cancel(self._create_job)
            self._create_job = None
        self.root.destroy()
