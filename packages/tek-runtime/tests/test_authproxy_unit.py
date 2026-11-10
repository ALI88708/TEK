"""Unit tests for authproxy.py.

Covers:
  - _RateLimiter: sliding window, thread safety, reset
  - _SessionState: atomic mark_ready, snapshot consistency
  - AuthProxy: pipe tracking, stop() cleanup
  - Integration: real socketpair + live HTTP server for 503 guard
    and pipe close on stop().

Each test is labelled UNIT, INTEGRATION (real sockets, no network),
or NOT_RUN (requires running stack / Kaggle).
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.request

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
from tek_runtime.authproxy import _RateLimiter, _SessionState, AuthProxy, _pipe
from tek_runtime.crypto import generate_secret


# ======================================================================
# UNIT — _RateLimiter
# ======================================================================

class TestRateLimiter:
    def test_allows_up_to_max(self):  # UNIT
        rl = _RateLimiter(max_attempts=3, window_s=60)
        assert all(rl.is_allowed("k") for _ in range(3))

    def test_blocks_after_max(self):  # UNIT
        rl = _RateLimiter(max_attempts=3, window_s=60)
        for _ in range(3):
            rl.is_allowed("k")
        assert rl.is_allowed("k") is False

    def test_different_keys_independent(self):  # UNIT
        rl = _RateLimiter(max_attempts=1, window_s=60)
        rl.is_allowed("a")
        assert rl.is_allowed("a") is False
        assert rl.is_allowed("b") is True

    def test_reset_clears_counter(self):  # UNIT
        rl = _RateLimiter(max_attempts=1, window_s=60)
        rl.is_allowed("k")
        assert rl.is_allowed("k") is False
        rl.reset("k")
        assert rl.is_allowed("k") is True

    def test_window_expiry_resets(self):  # UNIT
        rl = _RateLimiter(max_attempts=1, window_s=0)
        rl.is_allowed("k")
        time.sleep(0.01)
        assert rl.is_allowed("k") is True

    def test_thread_safe(self):  # UNIT
        rl = _RateLimiter(max_attempts=200, window_s=60)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(20):
                    rl.is_allowed("shared")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ======================================================================
# UNIT — _SessionState
# ======================================================================

class TestSessionState:
    def test_not_ready_before_mark(self):  # UNIT
        s = _SessionState()
        assert s.ready is False

    def test_ready_after_mark(self):  # UNIT
        s = _SessionState()
        s.mark_ready("s_X", '{"ok":true}', "host.example")
        assert s.ready is True

    def test_snapshot_consistent_after_mark(self):  # UNIT
        s = _SessionState()
        s.mark_ready("s_ABC", '{"desc":1}', "myhost")
        ready, sid, desc, host = s.snapshot()
        assert ready is True
        assert sid  == "s_ABC"
        assert desc == '{"desc":1}'
        assert host == "myhost"

    def test_snapshot_before_mark_returns_pending(self):  # UNIT
        s = _SessionState()
        ready, sid, desc, host = s.snapshot()
        assert ready is False
        assert sid == "pending"

    def test_concurrent_mark_and_read(self):  # UNIT
        """snapshot() must never see _ready=True with stale descriptor_json."""
        s = _SessionState()
        seen_bad = []

        def reader():
            for _ in range(500):
                ready, _, desc, _ = s.snapshot()
                if ready and desc == "{}":
                    seen_bad.append(True)
                time.sleep(0)

        def writer():
            time.sleep(0.001)
            s.mark_ready("s_ID", '{"real":1}', "h")

        r = threading.Thread(target=reader)
        w = threading.Thread(target=writer)
        r.start(); w.start()
        r.join();  w.join()
        assert not seen_bad, "Saw _ready=True with stale descriptor_json"


# ======================================================================
# UNIT — AuthProxy pipe tracking
# ======================================================================

class TestPipeTracking:
    def _proxy(self) -> AuthProxy:
        return AuthProxy(secret=generate_secret())

    def test_register_adds_to_list(self):  # UNIT
        p = self._proxy()
        a, b = socket.socketpair()
        try:
            p._register_pipe(a, b)
            assert len(p._active_pipes) == 1
        finally:
            a.close(); b.close()

    def test_unregister_removes_by_client(self):  # UNIT
        p = self._proxy()
        a, b = socket.socketpair()
        try:
            p._register_pipe(a, b)
            p._unregister_pipe(a)
            assert len(p._active_pipes) == 0
        finally:
            a.close(); b.close()

    def test_stop_closes_sockets_and_clears_list(self):  # UNIT
        p = self._proxy()
        a, b = socket.socketpair()
        p._register_pipe(a, b)
        p.stop()   # _server is None — must not raise

        assert len(p._active_pipes) == 0
        with pytest.raises(OSError):
            a.recv(1)
        with pytest.raises(OSError):
            b.recv(1)

    def test_stop_no_pipes_is_safe(self):  # UNIT
        p = self._proxy()
        p.stop()   # must not raise

    def test_multiple_pipes_all_closed(self):  # UNIT
        p = self._proxy()
        pairs = [socket.socketpair() for _ in range(3)]
        for a, b in pairs:
            p._register_pipe(a, b)
        p.stop()
        assert len(p._active_pipes) == 0
        for a, b in pairs:
            with pytest.raises(OSError):
                a.recv(1)


# ======================================================================
# INTEGRATION — live HTTP server (loopback, no external network)
# ======================================================================

def _start_proxy_server(proxy: AuthProxy) -> int:
    """Start proxy on an ephemeral port, return port."""
    import http.server, socketserver
    from tek_runtime.authproxy import _Handler, _Server
    # Patch port to 0 for ephemeral
    import tek_runtime.authproxy as _ap
    old = _ap._PROXY_PORT

    # We'll use a custom approach: build server directly on port 0
    class _EphemeralServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        # _Handler.proxy is a property reading self.server._proxy
        # so we just store _proxy here before any request arrives.

    srv = _EphemeralServer(("127.0.0.1", 0), _Handler)
    srv._proxy = proxy   # read by _Handler.proxy property
    proxy._server = srv
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    proxy._thread = t
    return srv.server_address[1]


class TestLiveProxy:
    """Integration tests that start a real HTTP server on loopback."""

    def _make_proxy(self, ready=False) -> tuple[AuthProxy, int]:
        secret = generate_secret()
        p = AuthProxy(secret=secret)
        if ready:
            p.mark_ready("s_TEST01", '{"schema":"tek.session.v0"}', "host.local")
        port = _start_proxy_server(p)
        return p, port

    def _get(self, port: int, path: str, headers: dict | None = None
             ) -> tuple[int, bytes]:
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_503_before_mark_ready(self):  # INTEGRATION
        """Auth endpoints return 503 before mark_ready() is called."""
        p, port = self._make_proxy(ready=False)
        try:
            # /tek/descriptor without mark_ready
            from tek_runtime.crypto import descriptor_token
            token = descriptor_token(p.secret)
            code, body = self._get(
                port, "/tek/descriptor",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert code == 503, f"Expected 503, got {code}"
            data = json.loads(body)
            assert data["code"] == "NOT_READY"
        finally:
            p.stop()

    def test_descriptor_accessible_after_mark_ready(self):  # INTEGRATION
        p, port = self._make_proxy(ready=True)
        try:
            from tek_runtime.crypto import descriptor_token
            token = descriptor_token(p.secret)
            code, body = self._get(
                port, "/tek/descriptor",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert code == 200, f"Expected 200, got {code}"
            data = json.loads(body)
            assert data["schema"] == "tek.session.v0"
        finally:
            p.stop()

    def test_rate_limit_returns_429(self):  # INTEGRATION
        p, port = self._make_proxy(ready=True)
        p.rate_limiter = _RateLimiter(max_attempts=2, window_s=60)
        try:
            # Exhaust the limit with POST /tek/auth
            for _ in range(2):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/tek/auth",
                    data=b'{"token":"bad"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    urllib.request.urlopen(req, timeout=5)
                except urllib.error.HTTPError:
                    pass
            # Third attempt must be rate-limited
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/tek/auth",
                data=b'{"token":"bad"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=5)
                assert False, "Should have raised"
            except urllib.error.HTTPError as e:
                assert e.code == 429, f"Expected 429, got {e.code}"
        finally:
            p.stop()

    def test_stop_while_pipe_active(self):  # INTEGRATION (real socketpair)
        """stop() closes a registered pipe and the peer sockets raise OSError."""
        p, port = self._make_proxy(ready=True)
        a, b = socket.socketpair()
        p._register_pipe(a, b)

        p.stop()

        assert len(p._active_pipes) == 0
        with pytest.raises(OSError):
            a.recv(1)
        with pytest.raises(OSError):
            b.recv(1)


# ======================================================================
# NOT_RUN markers
# ======================================================================

@pytest.mark.skip(reason="NOT_RUN: requires noVNC + websockify on 6081")
def test_websocket_upgrade_and_pipe_e2e():
    pass

@pytest.mark.skip(reason="NOT_RUN: requires real Cloudflare tunnel for Origin header")
def test_origin_check_with_tunnel_host():
    pass


# ======================================================================
# WebSocket pipe — real bidirectional data flow (socketpair, no network)
# ======================================================================

class TestPipeE2E:
    """Integration: exercise _pipe() with real sockets and real data."""

    def test_data_flows_bidirectionally(self):
        """INTEGRATION: bytes sent on one side arrive on the other."""
        import threading
        from tek_runtime.authproxy import _pipe

        a, b = socket.socketpair()
        result_a_to_b = []
        result_b_to_a = []

        def run_pipe():
            _pipe(a, b)

        t = threading.Thread(target=run_pipe, daemon=True)
        t.start()

        # a → b
        a.sendall(b"hello from a")
        data_b = b""
        while len(data_b) < len(b"hello from a"):
            chunk = b.recv(64)
            if not chunk:
                break
            data_b += chunk
        result_a_to_b.append(data_b)

        # b → a
        b.sendall(b"hello from b")
        data_a = b""
        while len(data_a) < len(b"hello from b"):
            chunk = a.recv(64)
            if not chunk:
                break
            data_a += chunk
        result_b_to_a.append(data_a)

        # Close both sides to terminate the pipe
        a.close()
        b.close()
        t.join(timeout=3)

        assert result_a_to_b[0] == b"hello from a"
        assert result_b_to_a[0] == b"hello from b"

    def test_pipe_terminates_when_one_side_closes(self):
        """INTEGRATION: _pipe() must return when one socket is closed."""
        import threading
        from tek_runtime.authproxy import _pipe

        a, b = socket.socketpair()
        done = threading.Event()

        def run_pipe():
            _pipe(a, b)
            done.set()

        t = threading.Thread(target=run_pipe, daemon=True)
        t.start()

        a.close()   # close one side
        assert done.wait(timeout=5), "_pipe() did not terminate within 5 s"
        b.close()

    def test_proxy_stop_unblocks_active_pipe(self):
        """INTEGRATION: proxy.stop() must unblock a _pipe() that is waiting."""
        import threading
        from tek_runtime.authproxy import _pipe

        proxy = AuthProxy(secret=generate_secret())
        a, b = socket.socketpair()
        proxy._register_pipe(a, b)

        done = threading.Event()

        def run_pipe():
            _pipe(a, b)
            done.set()

        t = threading.Thread(target=run_pipe, daemon=True)
        t.start()

        time.sleep(0.1)
        proxy.stop()   # must close a and b, unblocking _pipe()

        assert done.wait(timeout=5), "proxy.stop() did not unblock the pipe within 5 s"
