"""END-TO-END (local): real TekSession -> real QEMU -> real websockify -> real AuthProxy.

Only two things are replaced: the Cloudflare tunnel (a fake https URL string) and the
apt installs. Everything else is the shipped code path. This does NOT prove Cloudflare,
TLS, Kaggle, or a Windows controller work.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tek-runtime"))
sys.path.insert(0, str(ROOT / "tek-controller"))

websocket = pytest.importorskip("websocket")
pytestmark = pytest.mark.skipif(
    not (shutil.which("qemu-system-x86_64") and shutil.which("websockify")),
    reason="needs qemu-system-x86_64 and websockify installed",
)

import tek_runtime.qemu as qemu
import tek_runtime.session as sess_mod
from tek_runtime.crypto import auth_token, descriptor_token, generate_secret
from tek_runtime.guest_config import GuestConfig
from tek_runtime.plan import PlanError

HOST = "e2e-local.trycloudflare.com"
BASE = "http://127.0.0.1:6080"
ORIGIN = f"https://{HOST}"          # what a browser on the tunnel URL would send


def _port_free(p: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


@pytest.fixture
def live(tmp_path, monkeypatch):
    if not (_port_free(6080) and _port_free(6081)):
        pytest.skip("ports 6080/6081 busy")
    iso = tmp_path / "blank.iso"
    iso.write_bytes(b"\x00" * (2 * 1024 * 1024))
    monkeypatch.setattr(sess_mod.deps, "install_all", lambda: None)
    monkeypatch.setattr(sess_mod.tunnel, "start", lambda *a, **k: f"https://{HOST}")
    monkeypatch.setattr(sess_mod.tunnel, "stop", lambda: None)
    qemu._POWERDOWN_WAIT_S, qemu._SIGTERM_WAIT_S = 1, 5
    secret = generate_secret()
    guest = GuestConfig.from_local(str(iso), name="E2E Test OS", vcpu=1, ram_mb=256)
    s = sess_mod.TekSession(secret=secret, guest=guest)
    try:
        s.start()
    except PlanError as exc:
        pytest.skip(f"sandbox too small: {exc}")
    yield s, secret
    s.stop()


def _http(method, path, headers=None, body=None):
    req = urllib.request.Request(BASE + path, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _login_cookie(secret) -> str:
    code, hdrs, _ = _http("POST", "/tek/auth", {"Content-Type": "application/json"},
                          json.dumps({"token": auth_token(secret)}).encode())
    assert code == 204
    return hdrs["Set-Cookie"].split(";")[0]          # "tek_session=<value>"


def test_health_descriptor_and_controller_compat(live):
    s, secret = live
    assert _http("GET", "/tek/health")[0] == 200
    code, _, body = _http("GET", "/tek/descriptor", {"Authorization": f"Bearer {descriptor_token(secret)}"})
    assert code == 200
    from tek_controller.descriptor import parse_descriptor      # the CONTROLLER's parser
    from tek_controller.crypto import fingerprint
    d = parse_descriptor(body.decode(), check_expiry=True)
    assert d.guest.os == "E2E Test OS"
    assert json.loads(body)["secret_fingerprint"] == fingerprint(secret)
    assert _http("GET", "/tek/descriptor", {"Authorization": "Bearer wrong"})[0] == 401
    assert _http("GET", "/tek/descriptor")[0] == 401


def test_vnc_through_authproxy_requires_cookie_and_streams_rfb(live):
    s, secret = live
    with pytest.raises(websocket.WebSocketBadStatusException) as e:
        websocket.create_connection("ws://127.0.0.1:6080/websockify", subprotocols=["binary"], timeout=10, origin=ORIGIN)
    assert e.value.status_code == 401                          # auth BEFORE upgrade
    ws = websocket.create_connection("ws://127.0.0.1:6080/websockify", cookie=_login_cookie(secret),
                                     subprotocols=["binary"], timeout=10, origin=ORIGIN)
    banner = ws.recv()
    assert bytes(banner).startswith(b"RFB "), banner           # real VNC server behind the proxy
    ws.close()


def test_websocket_with_wrong_origin_is_rejected_even_with_valid_cookie(live):
    s, secret = live
    with pytest.raises(websocket.WebSocketBadStatusException) as e:
        websocket.create_connection("ws://127.0.0.1:6080/websockify", cookie=_login_cookie(secret),
                                    subprotocols=["binary"], timeout=10, origin="https://evil.example")
    assert e.value.status_code == 403


def test_metrics_with_cookie_show_real_qemu(live):
    s, secret = live
    assert _http("GET", "/tek/metrics")[0] == 401
    code, _, body = _http("GET", "/tek/metrics", {"Cookie": _login_cookie(secret)})
    data = json.loads(body)
    assert code == 200 and data["qemu"]["running"] is True
    assert {p["name"]: p["running"] for p in data["procs"]}["qemu-system-x86_64"] is True
    dump = body.decode().lower()
    assert "secret" not in dump and "password" not in dump


def test_terminal_executes_command_on_host(live):
    s, secret = live
    ws = websocket.create_connection("ws://127.0.0.1:6080/tek/terminal",
                                     cookie=_login_cookie(secret), timeout=10, origin=ORIGIN)
    ws.send("echo TEK_E2E_$((20+22))\n")
    got = ""
    deadline = time.time() + 8
    while time.time() < deadline and "TEK_E2E_42" not in got:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            break
        got += msg if isinstance(msg, str) else bytes(msg).decode(errors="replace")
    ws.close()
    assert "TEK_E2E_42" in got, got


def test_stop_closes_open_websocket_and_cleans_everything(live):
    s, secret = live
    ws = websocket.create_connection("ws://127.0.0.1:6080/websockify", cookie=_login_cookie(secret),
                                     subprotocols=["binary"], timeout=10, origin=ORIGIN)
    ws.recv()
    pid = qemu.pid()
    s.stop()
    ws.settimeout(10)
    with pytest.raises(Exception):                             # closed by the proxy
        while True:
            ws.recv()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert _port_free(6080) and _port_free(6081)
    assert sess_mod._active_session is None
    assert qemu.foreign_qemu_pids() == []


# ====================================================================================
# The CONTROLLER's own network functions against the real runtime (loopback http only;
# TLS + Cloudflare remain untested). The cookie is minted by the controller exactly as
# TekControllerApp._session_cookie_value() does.
# ====================================================================================
LOOP = "127.0.0.1:6080"


def _controller_cookie(s, secret) -> str:
    from tek_controller.crypto import make_cookie_value
    return make_cookie_value(secret, s.session_id, int(time.time()) + 900)


def test_controller_fetch_descriptor_against_real_runtime(live):
    s, secret = live
    from tek_controller.connect import ConnectError, fetch_descriptor
    d = fetch_descriptor(secret, LOOP, scheme="http")
    assert d["session_id"] == s.session_id and d["guest"]["os"] == "E2E Test OS"
    with pytest.raises(ConnectError) as e:
        fetch_descriptor(generate_secret(), LOOP, scheme="http")        # wrong secret
    assert e.value.code == "AUTH_FAILED"


def test_controller_minted_cookie_is_accepted_by_runtime(live):
    s, secret = live
    from tek_controller.connect import ConnectError, fetch_metrics
    m = fetch_metrics(secret, LOOP, _controller_cookie(s, secret), scheme="http")
    assert m["qemu"]["running"] is True and m["cpu"]["count"] >= 1
    from tek_controller.crypto import make_cookie_value
    for bad in (make_cookie_value(secret, "s_OTHERSESSION", int(time.time()) + 900),   # other session
                make_cookie_value(generate_secret(), s.session_id, int(time.time()) + 900),  # other secret
                make_cookie_value(secret, s.session_id, int(time.time()) - 5)):            # expired
        with pytest.raises(ConnectError) as e:
            fetch_metrics(secret, LOOP, bad, scheme="http")
        assert e.value.code == "AUTH_FAILED"


def test_plain_http_is_refused_for_non_loopback_hosts():
    from tek_controller.connect import fetch_descriptor
    with pytest.raises(ValueError):
        fetch_descriptor(generate_secret(), "evil.example.com", scheme="http")


def test_kickoff_v2_urls_are_single_use_but_unlimited(live):
    """Each fresh URL sets the cookie once; replay -> 410; a new URL works again (= Reconnect)."""
    s, secret = live
    from tek_controller.connect import build_kickoff_url
    from tek_controller.crypto import kickoff_token_v2

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    def hit(url):
        path = url.split(HOST, 1)[1]
        try:
            r = opener.open(BASE + path, timeout=10)
            return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

    u1 = build_kickoff_url(secret, HOST)
    assert "t=" not in u1.split("?", 1)[1].split("&")[0] and "k=" in u1
    code, hdrs = hit(u1)
    assert code == 302 and hdrs["Location"] == "/vnc.html"
    assert "HttpOnly" in hdrs["Set-Cookie"] and "SameSite=Strict" in hdrs["Set-Cookie"]
    assert hit(u1)[0] == 410                                    # replay refused
    assert hit(build_kickoff_url(secret, HOST))[0] == 302       # fresh URL = reconnect works
    assert hit(build_kickoff_url(generate_secret(), HOST))[0] == 401          # wrong secret
    ts = int(time.time()) - 400
    assert hit(f"https://{HOST}/tek/kickoff?ts={ts}&n=abcdefgh12345678&k={kickoff_token_v2(secret, ts, 'abcdefgh12345678')}")[0] == 401  # expired
    assert hit(f"https://{HOST}/tek/kickoff?ts=oops&n=x&k=y")[0] == 401      # malformed
