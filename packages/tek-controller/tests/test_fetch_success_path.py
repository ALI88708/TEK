"""Regression for the real root cause of 'Fetch & Connect hangs forever'.

fetch_descriptor() used `desc.get(...)` on a SessionDescriptor object, so EVERY successful
fetch raised AttributeError inside the worker thread (only ConnectError was caught) and the
UI stayed on 'AUTHENTICATING' forever. Earlier tests only exercised failure paths.
"""
import http.server
import json
import socketserver
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tek_controller.connect import ConnectError, fetch_descriptor, fetch_with_retry
from tek_controller.crypto import descriptor_token, fingerprint, generate_secret


def _descriptor(secret, *, fp=None):
    now = datetime.now(timezone.utc)
    f = "%Y-%m-%dT%H:%M:%SZ"
    return {
        "schema": "tek.session.v0", "protocol": "tek/0", "session_id": "s_TESTSUCCES",
        "created_at": now.strftime(f), "expires_at": (now + timedelta(hours=1)).strftime(f),
        "runtime_version": "0.1.0", "secret_fingerprint": fp or fingerprint(secret),
        "display": {"transport": "vnc", "url": "https://abc-def.trycloudflare.com/vnc.html",
                    "password_scheme": "hkdf-sha256/v1", "geometry": [1280, 800]},
        "resources": {"vcpu": 3, "ram_mb": 4096, "disk_gb": 10.0},
        "guest": {"os": "Any OS", "state": "ready"},
    }


@pytest.fixture
def server():
    state = {"secret": generate_secret(), "fp": None, "code": 200}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != f"Bearer {descriptor_token(state['secret'])}":
                self.send_response(401); self.end_headers(); return
            body = json.dumps(_descriptor(state["secret"], fp=state["fp"])).encode()
            self.send_response(state["code"]); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["host"] = f"127.0.0.1:{srv.server_address[1]}"
    yield state
    srv.shutdown(); srv.server_close()


def test_successful_fetch_returns_validated_dict(server):
    d = fetch_descriptor(server["secret"], server["host"], scheme="http")
    assert isinstance(d, dict) and d["session_id"] == "s_TESTSUCCES"
    assert d["secret_fingerprint"] == fingerprint(server["secret"])


def test_json_roundtrip_matches_what_the_ui_layer_does(server):
    d = fetch_descriptor(server["secret"], server["host"], scheme="http")
    from tek_controller.descriptor import parse_descriptor
    assert parse_descriptor(json.dumps(d, indent=2)).guest.os == "Any OS"   # app._on_fetch_ok does this


def test_fingerprint_mismatch_is_auth_failed(server):
    server["fp"] = "deadbeef"
    with pytest.raises(ConnectError) as e:
        fetch_descriptor(server["secret"], server["host"], scheme="http")
    assert e.value.code == "AUTH_FAILED"
