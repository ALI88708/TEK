"""Regression tests for the Update 7 wiring bugs.

Bug 1 — DashboardView built its Open VNC / Open Terminal buttons against
        ``self._on_open_vnc`` / ``self._on_open_terminal`` but never stored
        them, so every click raised AttributeError.

Bug 2 — the controller never minted a session cookie. ``/tek/metrics`` and
        ``/tek/terminal`` both require ``tek_session``, so the control panel
        and the terminal window could only ever receive 401.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tek-runtime"))

tk = pytest.importorskip("tkinter")

from tek_controller.app import TekControllerApp
from tek_controller.crypto import generate_secret, make_cookie_value
from tek_runtime.crypto import make_cookie_value as runtime_make_cookie_value
from tek_runtime.crypto import verify_cookie_value as runtime_verify_cookie_value

SESSION_ID = "s_TEST123456"

DESCRIPTOR = {
    "schema": "tek.session.v0",
    "protocol": "tek/0",
    "session_id": SESSION_ID,
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


# --------------------------------------------------------------------------- #
# Bug 2 — controller must mint a cookie the runtime accepts                    #
# --------------------------------------------------------------------------- #

def test_controller_cookie_matches_runtime_cookie() -> None:
    """Both sides derive the same cookie string from the same inputs."""
    secret = generate_secret()
    expiry = int(time.time()) + 900

    assert make_cookie_value(secret, SESSION_ID, expiry) == (
        runtime_make_cookie_value(secret, SESSION_ID, expiry)
    )


def test_controller_cookie_passes_runtime_verification() -> None:
    secret = generate_secret()
    expiry = int(time.time()) + 900
    cookie = make_cookie_value(secret, SESSION_ID, expiry)

    assert runtime_verify_cookie_value(secret, SESSION_ID, cookie)
    assert not runtime_verify_cookie_value(secret, "s_OTHER12345", cookie)
    assert not runtime_verify_cookie_value(generate_secret(), SESSION_ID, cookie)


def test_controller_cookie_expires() -> None:
    secret = generate_secret()
    expiry = int(time.time()) - 1
    cookie = make_cookie_value(secret, SESSION_ID, expiry)

    assert not runtime_verify_cookie_value(secret, SESSION_ID, cookie)


# --------------------------------------------------------------------------- #
# Bug 1 + Bug 2 — app-level wiring                                            #
# --------------------------------------------------------------------------- #

def _make_root() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - headless environments
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    return root


def _buttons(widget: tk.Misc) -> dict[str, tk.Button]:
    found: dict[str, tk.Button] = {}
    for child in widget.winfo_children():
        if isinstance(child, tk.Button):
            try:
                found[child.cget("text")] = child
            except tk.TclError:  # pragma: no cover - destroyed widget
                pass
        found.update(_buttons(child))
    return found


def test_dashboard_open_buttons_call_app_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clicking Open VNC / Open Terminal must reach the app handlers."""
    calls: list[str] = []
    monkeypatch.setattr(
        TekControllerApp, "open_vnc_window", lambda self: calls.append("vnc")
    )
    monkeypatch.setattr(
        TekControllerApp, "open_terminal_window", lambda self: calls.append("terminal")
    )

    root = _make_root()
    app = TekControllerApp(
        root, settings_path=tmp_path / "settings.json", create_delay_ms=0
    )
    try:
        buttons = _buttons(app.dashboard)
        assert "Open VNC" in buttons
        assert "Open Terminal" in buttons

        buttons["Open VNC"].invoke()
        buttons["Open Terminal"].invoke()

        assert calls == ["vnc", "terminal"]
    finally:
        root.destroy()


def test_connect_mints_a_verifiable_session_cookie(tmp_path: Path) -> None:
    """After a successful fetch the controller holds a usable cookie."""
    root = _make_root()
    app = TekControllerApp(
        root, settings_path=tmp_path / "settings.json", create_delay_ms=0
    )
    try:
        app.control_panel_view.start_polling = lambda: None  # no timers in tests
        secret = generate_secret()

        app._on_fetch_ok(secret, "example-words.trycloudflare.com", DESCRIPTOR)

        cookie = app._session_cookie_value()
        assert cookie, "controller must mint a session cookie after connect"
        assert runtime_verify_cookie_value(secret, SESSION_ID, cookie)
        assert app._fetch_live_metrics() is None or isinstance(
            app._fetch_live_metrics(), dict
        )
    finally:
        root.destroy()


def test_no_session_means_no_cookie(tmp_path: Path) -> None:
    root = _make_root()
    app = TekControllerApp(
        root, settings_path=tmp_path / "settings.json", create_delay_ms=0
    )
    try:
        assert app._session_cookie_value() == ""
        assert app._fetch_live_metrics() is None
    finally:
        root.destroy()
