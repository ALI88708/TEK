"""GUI smoke tests: the window builds, navigates, and stays honest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from tek_controller.app import TekControllerApp
from tek_controller.session import SessionState

VALID_DESCRIPTOR = json.dumps(
    {
        "schema": "tek.session.v0",
        "protocol": "tek/0",
        "session_id": "s_TEST123456",
        "created_at": "2026-10-30T10:00:00Z",
        "expires_at": "2099-10-30T22:00:00Z",
        "runtime_version": "0.1.0",
        "secret_fingerprint": "9f2c1a7b",
        "display": {
            "transport": "vnc",
            "url": "https://example-words.trycloudflare.com/vnc.html",
            "password_scheme": "hkdf-sha256/v1",
            "geometry": [1280, 800],
        },
        "resources": {"vcpu": 3, "ram_mb": 24576, "disk_gb": 17.5},
        "guest": {"os": "alpine", "state": "ready"},
    }
)


@pytest.fixture
def app(tmp_path: Path):
    root = _make_root()
    application = TekControllerApp(
        root,
        settings_path=tmp_path / "settings.json",
        create_delay_ms=0,
    )
    yield application
    root.destroy()


def _make_root() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - headless environments
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    return root


def test_window_builds_with_branding(app: TekControllerApp) -> None:
    assert "TEK" in app.brand_label.cget("text").upper()
    assert app.session.state is SessionState.IDLE


def test_container_holds_only_the_three_views(app: TekControllerApp) -> None:
    children = {str(child) for child in app.container.winfo_children()}
    assert children == {str(view) for view in app.views.values()}


def test_only_the_active_view_is_managed(app: TekControllerApp) -> None:
    for name in ("connection", "settings", "dashboard"):
        app.show_view(name)
        app.root.update()
        managed = [
            key for key, view in app.views.items() if view.winfo_manager() == "grid"
        ]
        assert managed == [name]


def test_default_view_is_dashboard(app: TekControllerApp) -> None:
    assert app.current_view == "dashboard"


def test_navigation_switches_views(app: TekControllerApp) -> None:
    app.show_view("connection")
    assert app.current_view == "connection"
    assert app.views["connection"].winfo_ismapped() in (0, 1)

    app.show_view("settings")
    assert app.current_view == "settings"

    app.show_view("dashboard")
    assert app.current_view == "dashboard"


def test_create_session_switches_to_connection(app: TekControllerApp) -> None:
    app.create_session()
    assert app.session.state is SessionState.PREPARING
    assert app.session.session_id is None

    app.root.update()

    assert app.current_view == "connection"
    notice = app.notice_label.cget("text").lower()
    assert "connection" in notice
    assert "secret" in notice


def test_create_session_clears_a_loaded_descriptor(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text(VALID_DESCRIPTOR)
    app.connect()
    assert "s_TEST123456" in app.session_id_label.cget("text")

    app.create_session()

    assert app.session_id_label.cget("text") == "-"


def test_empty_descriptor_is_rejected_without_connecting(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.descriptor_input.delete("1.0", "end")
    app.connect()

    assert app.session.state is SessionState.IDLE
    assert app.connection_error_code == "EMPTY_DESCRIPTOR"
    assert app.connection_status_label.cget("text") != ""


def test_malformed_descriptor_is_rejected(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text('{"protocol": "tek/9"}')
    app.connect()

    assert app.session.state is SessionState.IDLE
    assert app.connection_error_code == "UNSUPPORTED_PROTOCOL"


def test_valid_descriptor_is_accepted(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text(VALID_DESCRIPTOR)
    app.connect()

    assert app.session.state is SessionState.IDLE
    assert app.connection_error_code is None
    status = app.connection_status_label.cget("text").lower()
    assert "valid" in status


def test_valid_descriptor_populates_session_summary(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text(VALID_DESCRIPTOR)
    app.connect()

    assert "s_TEST123456" in app.session_id_label.cget("text")


def test_descriptor_text_is_never_echoed_into_the_event_log(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text(VALID_DESCRIPTOR)
    app.connect()

    log_text = app.event_log.get("1.0", "end")
    assert "trycloudflare" not in log_text
    assert "9f2c1a7b" not in log_text


def test_clear_descriptor_resets_the_form(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text(VALID_DESCRIPTOR)
    app.connect()

    app.clear_descriptor()

    assert app.descriptor is None
    assert app.connection_error_code is None
    assert app.descriptor_input.get("1.0", "end").strip() == ""
    assert app.connection_status_label.cget("text") == "No descriptor loaded."


def test_event_log_can_be_cleared(app: TekControllerApp) -> None:
    assert app.event_log.get("1.0", "end").strip()

    app.dashboard.clear_log()

    assert app.event_log.get("1.0", "end").strip() == ""


def test_invalid_timeout_is_rejected_without_saving(
    app: TekControllerApp, tmp_path: Path
) -> None:
    app.show_view("settings")
    app.settings_view.timeout_var.set("0")

    assert app.save_preferences() is False
    assert not (tmp_path / "settings.json").exists()
    status = app.settings_view.status_label.cget("text").lower()
    assert "timeout" in status
    assert "5" in status and "120" in status


def test_settings_persist_from_the_ui(app: TekControllerApp, tmp_path: Path) -> None:
    app.show_view("settings")
    app.settings_view.scale_var.set(125)
    app.settings_view.grid_var.set(False)
    app.save_preferences()

    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored["scale_percent"] == 125
    assert stored["show_grid"] is False


def test_restore_defaults_resets_the_form(app: TekControllerApp) -> None:
    app.show_view("settings")
    app.settings_view.scale_var.set(125)
    app.settings_view.grid_var.set(False)
    app.restore_default_preferences()

    assert app.settings_view.scale_var.get() == 100
    assert app.settings_view.grid_var.get() is True


def test_save_failure_is_reported_without_crashing(
    app: TekControllerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated denial")

    monkeypatch.setattr("tek_controller.app.save_settings", fail)

    assert app.save_preferences() is False
    status = app.settings_view.status_label.cget("text").lower()
    assert "not writable" in status


def test_create_session_clears_the_connection_view(app: TekControllerApp) -> None:
    app.show_view("connection")
    app.set_descriptor_text(VALID_DESCRIPTOR)
    app.connect()
    assert app.connection_view.session_row.value.cget("text") == "s_TEST123456"

    app.create_session()

    assert app.connection_status_label.cget("text") == "No descriptor loaded."
    assert app.connection_view.session_row.value.cget("text") == "-"


def test_preparing_state_does_not_claim_a_live_runtime(app: TekControllerApp) -> None:
    app.create_session()

    hint = app.dashboard.hint_label.cget("text").lower()
    assert "no runtime link" in hint
    assert "provision" not in hint


def test_close_destroys_the_window_with_pending_work(tmp_path: Path) -> None:
    root = _make_root()
    application = TekControllerApp(
        root,
        settings_path=tmp_path / "settings.json",
        create_delay_ms=60_000,
    )
    application.create_session()
    assert application.current_view == "dashboard"

    application.close()

    with pytest.raises(tk.TclError):
        root.winfo_exists()


def test_sidebar_click_switches_views(app: TekControllerApp) -> None:
    item = app.sidebar._items["connection"]
    assert item.text_label.cget("text") == "Connection"

    app.root.deiconify()
    app.root.update()
    item.content.event_generate("<Button-1>", x=5, y=5)
    app.root.update()

    assert app.current_view == "connection"


def test_scale_segment_click_updates_the_setting(app: TekControllerApp) -> None:
    app.show_view("settings")
    app.root.deiconify()
    app.root.update()
    cell = app.settings_view.scale_control._cells[125]

    cell.event_generate("<Button-1>", x=5, y=5)
    app.root.update()

    assert app.settings_view.scale_var.get() == 125
