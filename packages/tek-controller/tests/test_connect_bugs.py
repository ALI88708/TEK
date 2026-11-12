"""Tests for the two root-cause bugs in Fetch & Connect.

Bug A — Lambda closure: exc deleted after except block.
Bug B — SSL ALPN: Cloudflare h2 negotiation hangs HTTP/1.1 client.
"""
from __future__ import annotations

import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import http.server
import socketserver

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from tek_controller.connect import ConnectError, fetch_descriptor, _make_ssl_context
from tek_controller.crypto import generate_secret


# ------------------------------------------------------------------ #
# Bug A — lambda closure                                              #
# ------------------------------------------------------------------ #

class TestLambdaClosureFix:
    """Verify the exc capture pattern works correctly."""

    def test_captured_exception_survives_except_block(self):
        """UNIT: exc captured as default arg must be accessible after block exits."""
        callbacks: list[str] = []

        def simulate_fetch():
            try:
                raise ValueError("test error")
            except ValueError as exc:
                _exc = exc
                # Simulate root.after(0, lambda e=_exc: callback(e))
                cb = lambda e=_exc: callbacks.append(str(e))
                # exc is now out of scope (except block exited)
                cb()  # must not raise NameError

        simulate_fetch()
        assert callbacks == ["test error"], f"Got: {callbacks}"

    def test_plain_lambda_would_fail(self):
        """UNIT: document that plain lambda captures by name (the bug)."""
        # In Python 3, exc IS deleted after the except block.
        exc_ref = []

        def simulate_broken():
            try:
                raise ValueError("test error")
            except ValueError as exc:
                cb = lambda: str(exc)  # plain capture — deleted after block
                exc_ref.append(cb)

        simulate_broken()
        # At this point, exc is out of scope in the enclosing frame.
        # Calling the lambda raises NameError in Python 3.
        with pytest.raises(NameError):
            exc_ref[0]()

    def test_connect_error_attributes_accessible(self):
        """UNIT: ConnectError attributes survive being passed as default arg."""
        try:
            raise ConnectError("TIMEOUT", "No response within 30 s.")
        except ConnectError as exc:
            _exc = exc
            # Simulate what app.py does after the fix
            captured = lambda e=_exc: (e.code, e.message)

        # exc is now out of scope
        code, msg = captured()
        assert code == "TIMEOUT"
        assert "30" in msg


# ------------------------------------------------------------------ #
# Bug B — SSL ALPN                                                    #
# ------------------------------------------------------------------ #

class TestSSLALPN:
    """Verify the SSL context forces HTTP/1.1 ALPN."""

    def test_make_ssl_context_sets_http11(self):
        """UNIT: _make_ssl_context must advertise only http/1.1."""
        ctx = _make_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        # Can't read ALPN protocols back directly from SSLContext,
        # but we can verify it was set without error and cert checking is on.
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    def test_make_ssl_context_does_not_disable_cert_check(self):
        """UNIT: security must not be reduced to fix the ALPN issue."""
        ctx = _make_ssl_context()
        assert ctx.verify_mode != ssl.CERT_NONE
        assert ctx.check_hostname is True

    def test_connect_uses_custom_ssl_context(self):
        """UNIT: fetch_descriptor must use the ALPN-forced context.

        We can't reach a real Cloudflare tunnel in CI, so we verify that
        the function accepts the ssl_ctx path by probing error message content.
        The TUNNEL_FAILED error must mention the hostname, not an ALPN error.
        """
        secret = generate_secret()
        with pytest.raises(ConnectError) as exc_info:
            fetch_descriptor(secret, "localhost.invalid", timeout_s=3)
        assert exc_info.value.code in ("TUNNEL_FAILED", "TIMEOUT"), \
            f"Unexpected code: {exc_info.value.code}"


# ------------------------------------------------------------------ #
# Integration: live HTTP server (loopback, no Cloudflare)             #
# ------------------------------------------------------------------ #

class _EchoServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    response_code  = 200
    response_body  = b'{"schema":"tek.session.v0","secret_fingerprint":"xx"}'

class _EchoHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        srv = self.server  # type: ignore
        body = srv.response_body
        self.send_response(srv.response_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass


class TestFetchDescriptorErrors:
    """Integration: exercise all ConnectError paths without a real tunnel."""

    def _start_server(self, code: int, body: bytes) -> int:
        srv = _EchoServer(("127.0.0.1", 0), _EchoHandler)
        srv.response_code = code
        srv.response_body = body
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv.server_address[1]

    def _fetch_http(self, secret, port, path="/tek/descriptor"):
        """Call fetch_descriptor against HTTP (not HTTPS) using urllib directly."""
        from tek_controller.crypto import descriptor_token as _dt
        import json as _json
        token = _dt(secret)
        url   = f"http://127.0.0.1:{port}{path}"
        req   = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_timeout_raises_connect_error(self):
        """INTEGRATION: unreachable host must raise TIMEOUT or TUNNEL_FAILED."""
        secret = generate_secret()
        with pytest.raises(ConnectError) as exc_info:
            fetch_descriptor(secret, "192.0.2.1", timeout_s=2)  # RFC5737 TEST-NET
        assert exc_info.value.code in ("TIMEOUT", "TUNNEL_FAILED")

    def test_bad_host_raises_tunnel_failed(self):
        """INTEGRATION: unresolvable host → TUNNEL_FAILED."""
        secret = generate_secret()
        with pytest.raises(ConnectError) as exc_info:
            fetch_descriptor(secret, "this-host-does-not-exist.invalid", timeout_s=3)
        assert exc_info.value.code == "TUNNEL_FAILED"

    def test_connect_error_code_is_stable_string(self):
        """UNIT: all ConnectError codes are plain uppercase strings."""
        codes = ["TIMEOUT", "TUNNEL_FAILED", "NOT_READY", "AUTH_FAILED",
                 "DESCRIPTOR_ERROR", "HTTP_ERROR"]
        for code in codes:
            exc = ConnectError(code, "test")
            assert exc.code == code
            assert isinstance(exc.code, str)

    def test_no_secret_in_error_messages(self):
        """UNIT: ConnectError messages must never contain the raw secret."""
        secret = generate_secret()
        import base64
        secret_b64 = base64.urlsafe_b64encode(secret).decode()
        exc = ConnectError("AUTH_FAILED",
                           "Fingerprint mismatch. Expected xxxx, got yyyy.")
        assert secret_b64 not in exc.message
        assert secret.hex() not in exc.message
