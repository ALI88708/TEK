"""Auth proxy — the only listener exposed through the Cloudflare tunnel.

Port 6080 (tunneled).

Session readiness:
  AuthProxy starts with _ready=False. No auth endpoint responds until
  mark_ready(session_id, descriptor_json, tunnel_host) is called, which
  sets all three fields under a lock and then atomically flips _ready.
  This eliminates the race where session_id is non-"pending" but
  descriptor_json is still "{}".

WebSocket lifecycle:
  Every active WebSocket pipe is tracked in _active_pipes (guarded by
  _pipes_lock). stop() closes all tracked sockets before shutting down
  the HTTP server, then waits briefly for pipe threads to notice and exit.

Rate limiting:
  /tek/auth and /tek/kickoff: max 10 attempts per IP per 5 minutes.

Security properties:
  - No secret, token, password, or cookie value appears in logs.
  - Origin/Sec-Fetch-Site checked on POST /tek/auth and WS upgrade.
  - WebSocket auth validated BEFORE the 101 response is sent.
  - Cookie: HttpOnly, Secure, SameSite=Strict, HMAC-signed, with expiry.
  - Kickoff token: single-use (boolean flag).
  - 503 returned on any auth request before mark_ready() is called.
"""
from __future__ import annotations

import http.server
import json
import mimetypes
import os
import socket
import socketserver
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import time as _time
from .crypto import (
    make_cookie_value,
    verify_auth_token,
    verify_cookie_value,
    verify_descriptor_token,
    verify_kickoff_token,
)

_NOVNC_ROOT   = Path("/usr/share/novnc")
_PROXY_PORT   = 6080
_BACKEND_HOST = "127.0.0.1"
_BACKEND_PORT = 6081
_COOKIE_NAME  = "tek_session"
_COOKIE_TTL   = 900   # 15 min


# ======================================================================
# Rate limiter
# ======================================================================

class _RateLimiter:
    """Per-key sliding-window counter. Thread-safe."""

    def __init__(self, max_attempts: int = 10, window_s: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_s     = window_s
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Return True and increment. Return False if limit exceeded."""
        now = time.time()
        with self._lock:
            count, win_start = self._counts.get(key, (0, now))
            if now - win_start > self.window_s:
                count, win_start = 0, now
            if count >= self.max_attempts:
                return False
            self._counts[key] = (count + 1, win_start)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._counts.pop(key, None)


# ======================================================================
# Session state bundle — set atomically by mark_ready()
# ======================================================================

class _SessionState:
    """Holds the three fields that must be consistent when _ready is True."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready          = False
        self._session_id     = "pending"
        self._descriptor_json = "{}"
        self._tunnel_host    = ""

    def mark_ready(
        self, session_id: str, descriptor_json: str, tunnel_host: str
    ) -> None:
        """Set all fields and flip _ready atomically under a lock."""
        with self._lock:
            self._session_id      = session_id
            self._descriptor_json = descriptor_json
            self._tunnel_host     = tunnel_host
            self._ready           = True   # written last

    def snapshot(self) -> tuple[bool, str, str, str]:
        """Return (ready, session_id, descriptor_json, tunnel_host) consistently."""
        with self._lock:
            return (
                self._ready,
                self._session_id,
                self._descriptor_json,
                self._tunnel_host,
            )

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready

    # Convenience setters kept for tests / proxy internal use
    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    @property
    def descriptor_json(self) -> str:
        with self._lock:
            return self._descriptor_json

    @property
    def tunnel_host(self) -> str:
        with self._lock:
            return self._tunnel_host


# ======================================================================
# Request handler
# ======================================================================

class _Handler(http.server.BaseHTTPRequestHandler):
    @property
    def proxy(self) -> "AuthProxy":
        """Access the AuthProxy via the server object.
        self.server is set by BaseRequestHandler.__init__ BEFORE handle()
        is called, so this property is always safe to use inside do_GET/do_POST.
        """
        return self.server._proxy  # type: ignore[attr-defined]


    def log_message(self, fmt: str, *args: object) -> None:
        pass   # never log — avoids accidental credential exposure

    # ------------------------------------------------------------------ #
    # Routing                                                              #
    # ------------------------------------------------------------------ #

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path   = parsed.path

        if path == "/tek/descriptor":
            self._handle_descriptor()
        elif path == "/tek/health":
            self._handle_health()
        elif path == "/tek/kickoff":
            qs = parse_qs(parsed.query)
            self._handle_kickoff(qs.get("t", [""])[0])
        elif path in ("/websockify", "/websockify/"):
            if self.headers.get("Upgrade", "").lower() == "websocket":
                self._handle_ws_upgrade()
            else:
                self._json(400, "BAD_REQUEST", "WebSocket upgrade required.")
        else:
            self._serve_static(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/tek/auth":
            self._handle_auth()
        else:
            self._json(404, "NOT_FOUND", "Not found.")

    # ------------------------------------------------------------------ #
    # Guards                                                               #
    # ------------------------------------------------------------------ #

    def _session_ready(self) -> bool:
        """Return False (and send 503) if mark_ready() has not been called."""
        if not self.proxy.state.ready:
            self._json(503, "NOT_READY",
                       "Session is initializing. Try again in a few seconds.")
            return False
        return True

    def _rate_check(self, key: str) -> bool:
        if not self.proxy.rate_limiter.is_allowed(key):
            self._json(429, "RATE_LIMITED",
                       "Too many attempts. Try again later.")
            return False
        return True

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    # ------------------------------------------------------------------ #
    # Endpoints                                                            #
    # ------------------------------------------------------------------ #

    def _handle_health(self) -> None:
        """Public health check — no authentication required.
        Returns 200 if the proxy is running (session may still be initializing).
        Returns 503 if the proxy is not yet ready to serve authenticated requests.
        """
        ready, sid, _, _ = self.proxy.state.snapshot()
        body = json.dumps({
            "status": "ready" if ready else "initializing",
            "session_ready": ready,
            "time": _time.time(),
        }).encode()
        code = 200 if ready else 503
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_descriptor(self) -> None:
        if not self._session_ready():
            return
        # Read session_id and descriptor_json from a single consistent snapshot.
        ready, sid, desc_json, _ = self.proxy.state.snapshot()
        if not ready:   # re-check under lock (belt-and-suspenders)
            self._json(503, "NOT_READY", "Session is initializing.")
            return

        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._json(401, "AUTH_REQUIRED", "Bearer token required.")
            return
        token = auth[7:]
        if not verify_descriptor_token(self.proxy.secret, token):
            self._json(401, "AUTH_FAILED", "Invalid descriptor token.")
            return

        body = desc_json.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_auth(self) -> None:
        if not self._session_ready():
            return
        ip = self._client_ip()
        if not self._rate_check(f"auth:{ip}"):
            return
        if not self._check_origin():
            self._json(403, "FORBIDDEN_ORIGIN", "Origin check failed.")
            return
        ct = self.headers.get("Content-Type", "")
        if "application/json" not in ct:
            self._json(400, "BAD_REQUEST", "Content-Type must be application/json.")
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 4096:
            self._json(400, "BAD_REQUEST", "Body too large.")
            return
        try:
            data  = json.loads(self.rfile.read(length))
            token = str(data.get("token", ""))
        except Exception:
            self._json(400, "BAD_REQUEST", "Invalid JSON body.")
            return
        if not verify_auth_token(self.proxy.secret, token):
            self._json(401, "AUTH_FAILED", "Invalid or expired auth token.")
            return
        _, sid, _, _ = self.proxy.state.snapshot()
        self._issue_cookie(sid)

    def _handle_kickoff(self, token: str) -> None:
        if not self._session_ready():
            return
        ip = self._client_ip()
        if not self._rate_check(f"kickoff:{ip}"):
            return
        p = self.proxy
        if p.kickoff_used:
            self._json(410, "AUTH_FAILED", "Kickoff token already used.")
            return
        if not verify_kickoff_token(p.secret, token):
            self._json(401, "AUTH_FAILED", "Invalid kickoff token.")
            return
        p.kickoff_used = True
        _, sid, _, _ = p.state.snapshot()
        self._issue_cookie(sid, redirect="/vnc.html")

    def _handle_ws_upgrade(self) -> None:
        if not self._session_ready():
            return
        if not self._check_origin():
            self.send_response(403)
            self.end_headers()
            return

        ready, sid, _, _ = self.proxy.state.snapshot()
        cookie = self._get_cookie(_COOKIE_NAME)
        if not cookie or not verify_cookie_value(self.proxy.secret, sid, cookie):
            self.send_response(401)
            self.send_header("WWW-Authenticate", "cookie")
            self.end_headers()
            return

        try:
            backend = socket.create_connection((_BACKEND_HOST, _BACKEND_PORT), timeout=5)
        except OSError:
            self.send_response(502)
            self.end_headers()
            return

        # Forward the upgrade request to websockify
        lines = [f"GET {self.path} HTTP/1.1\r\n"]
        for k, v in self.headers.items():
            if k.lower() == "host":
                lines.append(f"Host: {_BACKEND_HOST}:{_BACKEND_PORT}\r\n")
            else:
                lines.append(f"{k}: {v}\r\n")
        lines.append("\r\n")
        backend.sendall("".join(lines).encode())

        # Read backend 101 response
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = backend.recv(4096)
            if not chunk:
                backend.close()
                self.send_response(502)
                self.end_headers()
                return
            resp += chunk

        # Auth is verified — NOW send 101 to client
        sep = resp.index(b"\r\n\r\n") + 4
        self.wfile.write(resp[:sep])
        self.wfile.flush()

        leftover = resp[sep:]
        if leftover:
            try:
                self.connection.sendall(leftover)
            except OSError:
                backend.close()
                return

        client_sock = self.connection
        self.proxy._register_pipe(client_sock, backend)
        try:
            _pipe(client_sock, backend)
        finally:
            self.proxy._unregister_pipe(client_sock)

    def _serve_static(self, path: str) -> None:
        if ".." in path:
            self.send_error(400)
            return
        if path in ("/", ""):
            path = "/vnc.html"
        file_path = _NOVNC_ROOT / path.lstrip("/")
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        data = file_path.read_bytes()
        mt, _ = mimetypes.guess_type(str(file_path))
        self.send_response(200)
        self.send_header("Content-Type", mt or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _check_origin(self) -> bool:
        if self.headers.get("Sec-Fetch-Site", "") == "cross-site":
            return False
        origin = self.headers.get("Origin", "")
        host   = self.proxy.state.tunnel_host
        if origin and host and origin != f"https://{host}":
            return False
        return True

    def _get_cookie(self, name: str) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k.strip() == name:
                return v.strip()
        return None

    def _issue_cookie(self, session_id: str, redirect: str | None = None) -> None:
        expiry = int(time.time()) + _COOKIE_TTL
        cv = make_cookie_value(self.proxy.secret, session_id, expiry)
        cookie_header = (
            f"{_COOKIE_NAME}={cv}; HttpOnly; Secure; SameSite=Strict; "
            f"Path=/; Max-Age={_COOKIE_TTL}"
        )
        if redirect:
            self.send_response(302)
            self.send_header("Location", redirect)
            self.send_header("Set-Cookie", cookie_header)
            self.end_headers()
        else:
            self.send_response(204)
            self.send_header("Set-Cookie", cookie_header)
            self.end_headers()

    def _json(self, code: int, error_code: str, message: str) -> None:
        body = json.dumps({"code": error_code, "message": message}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ======================================================================
# Bidirectional socket pipe
# ======================================================================

def _pipe(a: socket.socket, b: socket.socket) -> None:
    """Bidirectional pipe. Blocks until both directions close."""
    done = threading.Event()

    def _fwd(src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            done.set()

    t = threading.Thread(target=_fwd, args=(a, b), daemon=True)
    t.start()
    _fwd(b, a)
    # Wait up to 2 s for the background thread to notice the socket close.
    t.join(timeout=2.0)


# ======================================================================
# HTTP Server
# ======================================================================

class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self, proxy: "AuthProxy") -> None:
        self._proxy = proxy
        super().__init__(("127.0.0.1", _PROXY_PORT), _Handler)

    # finish_request uses the default socketserver implementation.
    # _Handler.proxy is a property that reads self.server._proxy,
    # which is set in _Server.__init__ before any handler is created.


# ======================================================================
# AuthProxy — public interface
# ======================================================================

_PIPE_DRAIN_S = 0.5   # seconds to wait for pipe threads after closing sockets


class AuthProxy:
    def __init__(
        self,
        secret: bytes,
        session_id: str = "pending",
        descriptor_json: str = "{}",
        tunnel_host: str = "",
    ) -> None:
        self.secret       = secret
        self.state        = _SessionState()
        self.kickoff_used = False
        self.rate_limiter = _RateLimiter(max_attempts=10, window_s=300)

        # Active WebSocket pipe sockets
        self._active_pipes: list[tuple[socket.socket, socket.socket]] = []
        self._pipes_lock = threading.Lock()

        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #

    def mark_ready(
        self, session_id: str, descriptor_json: str, tunnel_host: str
    ) -> None:
        """Atomically publish session credentials. Must be called once,
        after all three values are available. Unblocks auth endpoints."""
        self.state.mark_ready(session_id, descriptor_json, tunnel_host)

    def start(self) -> None:
        self._server = _Server(self)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Close active WebSocket connections, then stop the HTTP server."""
        # 1. Force-close all tracked pipe sockets.
        with self._pipes_lock:
            for client_sock, backend_sock in self._active_pipes:
                for s in (client_sock, backend_sock):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        s.close()
                    except OSError:
                        pass
            self._active_pipes.clear()

        # 2. Brief pause: let _pipe() threads notice the closed sockets,
        #    call t.join(timeout=2.0), and exit cleanly before server.shutdown().
        time.sleep(_PIPE_DRAIN_S)

        # 3. Stop accepting new connections.
        if self._server:
            self._server.shutdown()

    # ------------------------------------------------------------------ #

    def _register_pipe(
        self, client: socket.socket, backend: socket.socket
    ) -> None:
        with self._pipes_lock:
            self._active_pipes.append((client, backend))

    def _unregister_pipe(self, client: socket.socket) -> None:
        with self._pipes_lock:
            self._active_pipes = [
                (c, b) for c, b in self._active_pipes if c is not client
            ]
