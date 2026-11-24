"""REAL Tk widgets (run under a display / xvfb): nothing here is mocked except the browser
launcher and, where stated, the network function being tested for UI behaviour."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tek-runtime"))
tk = pytest.importorskip("tkinter")

import tek_controller.app as app_mod
from tek_controller.app import TekControllerApp
from tek_controller.connect import ConnectError
from tek_controller.crypto import fingerprint, generate_secret, make_cookie_value
from tek_controller.session import SessionState


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    a = TekControllerApp(root, settings_path=tmp_path / "s.json", create_delay_ms=0)
    yield a
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel):
            try: w.destroy()
            except tk.TclError: pass
    root.destroy()


def pump(app, predicate, timeout=8.0):
    """Run the real Tk mainloop until `predicate()` or timeout (the app's worker threads call
    root.after(), which Tk only allows while a mainloop is running)."""
    end = time.time() + timeout

    def tick():
        if predicate() or time.time() > end:
            app.root.quit()
        else:
            app.root.after(20, tick)

    app.root.after(20, tick)
    app.root.mainloop()
    return predicate()


def _descriptor(secret):
    now, f = datetime.now(timezone.utc), "%Y-%m-%dT%H:%M:%SZ"
    return {"schema": "tek.session.v0", "protocol": "tek/0", "session_id": "s_GUITEST001",
            "created_at": now.strftime(f), "expires_at": (now + timedelta(hours=1)).strftime(f),
            "runtime_version": "0.1.0", "secret_fingerprint": fingerprint(secret),
            "display": {"transport": "vnc", "url": "https://gui-test.trycloudflare.com/vnc.html",
                        "password_scheme": "hkdf-sha256/v1", "geometry": [1280, 800]},
            "resources": {"vcpu": 2, "ram_mb": 2048, "disk_gb": 8.0},
            "guest": {"os": "Any OS", "state": "ready"}}


def _set_host(app, host="gui-test.trycloudflare.com"):
    app.connection_view.host_entry.delete(0, "end")
    app.connection_view.host_entry.insert(0, host)


# ---------------------------------------------------------------- navigation
def test_every_view_can_be_shown(app):
    for key in app.views:
        app.show_view(key); app.root.update()
        assert app.views[key].winfo_manager() == "grid"
    assert {"dashboard", "connection", "settings", "control_panel", "vm_config"} <= set(app.views)


# ---------------------------------------------------------------- never hang
def test_unexpected_exception_in_fetch_is_shown_not_swallowed(app, monkeypatch):
    app.connection_view.set_secret(generate_secret()); _set_host(app)
    def boom(*a, **k): raise RuntimeError("kaboom")
    monkeypatch.setattr(app_mod, "fetch_descriptor", boom)
    app.fetch_and_connect()
    assert pump(app, lambda: app.connection_view.code_label.cget("text") == "INTERNAL_ERROR")
    assert "kaboom" in app.connection_view.status_label.cget("text")


def test_connect_error_is_shown(app, monkeypatch):
    app.connection_view.set_secret(generate_secret()); _set_host(app)
    def fail(*a, **k): raise ConnectError("TIMEOUT", "no answer")
    monkeypatch.setattr(app_mod, "fetch_descriptor", fail)
    app.fetch_and_connect()
    assert pump(app, lambda: app.connection_view.code_label.cget("text") == "TIMEOUT")


def test_successful_fetch_reaches_running_through_real_threads(app, monkeypatch):
    secret = generate_secret()
    app.connection_view.set_secret(secret); _set_host(app)
    monkeypatch.setattr(app_mod, "fetch_descriptor", lambda *a, **k: _descriptor(secret))
    app.fetch_and_connect()
    assert pump(app, lambda: app.session.state is SessionState.RUNNING)
    assert app.connection_view.code_label.cget("text") == "READY"


# ---------------------------------------------------------------- VM config view
def _fill(view, **kw):
    view._iso_type.set(kw.get("iso_type", "url"))
    view._on_iso_type_change()
    view._iso_val.configure(state="normal"); view._iso_val.delete(0, "end"); view._iso_val.insert(0, kw.get("iso", ""))
    view._sha_val.configure(state="normal"); view._sha_val.delete(0, "end"); view._sha_val.insert(0, kw.get("sha", ""))
    view._name_val.delete(0, "end"); view._name_val.insert(0, kw.get("name", "My OS"))
    view._disk_var.set(kw.get("disk", 0)); view._cpu_var.set(kw.get("cpu", 0)); view._ram_var.set(kw.get("ram", 0))
    view._fw_var.set(kw.get("fw", "bios")); view._mt_var.set(kw.get("mt", "pc"))


def test_vm_config_generates_the_snippet_that_is_shown_and_logged(app):
    v = app.vm_config_view
    _fill(v, iso="https://example.com/os.iso", disk=10, cpu=2, ram=2048, fw="uefi", mt="q35")
    v._on_click_generate()
    shown = v._snippet.get("1.0", "end")
    assert "IsoSpec.from_url('https://example.com/os.iso'" in shown
    for frag in ("vcpu=2", "ram_mb=2048", "disk_size_gb=10.0", "firmware='uefi'", "machine='q35'"):
        assert frag in shown
    compile(shown, "<snippet>", "exec")
    assert "snippet generated" in app.dashboard.event_log.get("1.0", "end").lower()
    v._copy_snippet()
    assert v.clipboard_get().strip() == shown.strip()


def test_vm_config_invalid_input_shows_error_and_no_snippet(app):
    v = app.vm_config_view
    _fill(v, iso="ftp://nope")
    v._on_click_generate()
    assert "http" in v._status.cget("text").lower()
    assert v._snippet.get("1.0", "end").strip() == ""


def test_generating_a_snippet_does_not_touch_the_session_secret(app):
    s = generate_secret(); app.connection_view.set_secret(s)
    _fill(app.vm_config_view, iso="https://example.com/os.iso"); app.vm_config_view._on_click_generate()
    assert app.connection_view.get_secret() == s


# ---------------------------------------------------------------- control panel
def test_control_panel_shows_real_values_and_unavailable(app):
    cp = app.control_panel_view
    cp._update({"cpu": {"percent": 12.5, "count": 4}, "ram": {"used_mb": 1000, "percent": 5.0},
                "disk": {"free_gb": 9.5, "percent": 40.0}, "gpu": None,
                "qemu": {"running": True}, "procs": [{"name": "qemu-system-x86_64", "running": True}]})
    c = cp._cards
    assert "12.5" in c[0]._v.cget("text") and c[1]._v.cget("text").startswith("4")
    assert c[6]._v.cget("text") == "Unavailable" and c[7]._v.cget("text") == "Running"
    assert "✓ qemu-system-x86_64" in cp._procs.cget("text")
    cp._update(None)
    assert c[8]._v.cget("text") == "Disconnected"


# ---------------------------------------------------------------- VNC window
def test_vnc_reconnect_uses_a_fresh_single_use_url_each_time(app, monkeypatch):
    import tek_controller.views.vnc_window as vw
    opened = []
    monkeypatch.setattr(vw.webbrowser, "open", lambda u: opened.append(u) or True)
    app._live_host, app._live_secret = "gui-test.trycloudflare.com", generate_secret()
    app.open_vnc_window()
    win = next(w for w in app.root.winfo_children() if isinstance(w, vw.VncWindow))
    opened.clear()
    win._open(); win._open(); win._open()
    assert len(opened) == 3 and len(set(opened)) == 3, "every Reconnect must use a NEW url"
    assert all("/tek/kickoff?ts=" in u and "&k=" in u for u in opened)
    closed = []
    win._on_disconnect = lambda: closed.append(1)
    win._on_close()
    assert closed == [1]


# ---------------------------------------------------------------- terminal (REAL proxy)
def test_terminal_window_runs_a_command_through_a_real_authproxy(app):
    import socket
    from tek_runtime.authproxy import AuthProxy
    from tek_controller.views.terminal_window import TerminalWindow, _WS_AVAILABLE
    if not _WS_AVAILABLE:
        pytest.skip("websocket-client not installed")
    import os
    if not os.path.exists("/bin/bash"):
        pytest.skip("terminal endpoint spawns /bin/bash (Linux/Kaggle only)")
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 6080)) == 0:
            pytest.skip("port 6080 busy")
    secret, host = generate_secret(), "gui-test.trycloudflare.com"
    proxy = AuthProxy(secret=secret); proxy.start()
    proxy.mark_ready("s_GUITEST001", "{}", host)
    try:
        cookie = make_cookie_value(secret, "s_GUITEST001", int(time.time()) + 900)   # as the app mints it
        win = TerminalWindow(app.root, tunnel_host=host, session_cookie=cookie,
                             url="ws://127.0.0.1:6080/tek/terminal")
        assert pump(app, lambda: win._st.cget("text") == "Connected")
        win._inp.insert(0, "echo TEK_GUI_$((40+2))"); win._send()
        assert pump(app, lambda: "TEK_GUI_42" in win._out.get("1.0", "end")), win._out.get("1.0", "end")
        win._close()
    finally:
        proxy.stop()


def test_terminal_with_a_bad_cookie_reports_an_error_instead_of_hanging(app):
    import socket
    from tek_runtime.authproxy import AuthProxy
    from tek_controller.views.terminal_window import TerminalWindow, _WS_AVAILABLE
    if not _WS_AVAILABLE:
        pytest.skip("websocket-client not installed")
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 6080)) == 0:
            pytest.skip("port 6080 busy")
    secret, host = generate_secret(), "gui-test.trycloudflare.com"
    proxy = AuthProxy(secret=secret); proxy.start(); proxy.mark_ready("s_GUITEST001", "{}", host)
    try:
        win = TerminalWindow(app.root, tunnel_host=host, session_cookie="garbage",
                             url="ws://127.0.0.1:6080/tek/terminal")
        assert pump(app, lambda: "401" in win._out.get("1.0", "end") or "Error" in win._st.cget("text"))
        win._close()
    finally:
        proxy.stop()


def test_control_panel_polling_is_idempotent_and_thread_safe(app):
    calls = []
    cp = app.control_panel_view
    cp._on_refresh = lambda: calls.append(1) or {"cpu": {"percent": 1.0, "count": 2}, "ram": {}, "disk": {}, "gpu": None,
                                                 "qemu": {"running": True}, "procs": []}
    cp.start_polling(); cp.start_polling(); cp.start_polling()      # e.g. three reconnects
    assert pump(app, lambda: cp._cards[1]._v.cget("text").startswith("2"))
    assert len(calls) == 1, "re-starting polling must not stack refresh loops"
    cp.stop_polling()
    assert cp._job is None and cp._drain_job is None
