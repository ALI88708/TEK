"""Fetch and validate the session descriptor from the live runtime.

Root causes of the original "Fetch & Connect hangs forever" bug:

BUG A — Lambda closure (Python 3 exception scoping):
  In Python 3, the exception variable `exc` in an `except` clause is deleted
  when the clause exits.  The deferred lambda `lambda: self._on_fetch_error(exc)`
  captures `exc` by name, but `exc` is gone by the time `root.after()` runs it,
  causing a silent `NameError`.  Error callbacks never fire; the UI stays on
  "Fetching…" indefinitely.
  FIX: capture the exception before the except block exits:
    `except ConnectError as exc: _e=exc; self.root.after(0, lambda e=_e: cb(e))`
  (This fix lives in app.py where the lambda is built; connect.py documents it here.)

BUG B — SSL ALPN / HTTP-version mismatch with Cloudflare:
  Cloudflare Quick Tunnel (trycloudflare.com) advertises h2 (HTTP/2) during the
  TLS ALPN handshake.  Python's `http.client` / `urllib.request` negotiates h2
  but then sends an HTTP/1.1 request on the same socket.  Cloudflare waits ~2
  minutes for the HTTP/2 connection preface before closing the connection.
  FIX: build a custom ssl.SSLContext that restricts ALPN to ["http/1.1"] so
  Cloudflare serves HTTP/1.1 on this connection.

Connection phases (returned as ConnectError.code):
  TIMEOUT          — socket-level timeout, no data received
  TUNNEL_FAILED    — TCP/DNS failure, tunnel not reachable
  NOT_READY        — 503, runtime still initialising
  AUTH_FAILED      — 401 or fingerprint mismatch
  DESCRIPTOR_ERROR — descriptor JSON invalid or expired
  HTTP_ERROR       — other unexpected HTTP status
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request

from .crypto import descriptor_token, fingerprint
from .descriptor import DescriptorError, parse_descriptor

_DEFAULT_TIMEOUT_S = 30


class ConnectError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message


def _make_ssl_context() -> ssl.SSLContext:
    """Return an SSLContext that forces HTTP/1.1 ALPN.

    Without this, Cloudflare Quick Tunnel negotiates h2 during TLS, but
    Python's http.client speaks only HTTP/1.1 on the wire.  Cloudflare then
    waits ~2 min for the HTTP/2 preface before timing out.
    """
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


def fetch_descriptor(
    secret: bytes,
    host: str,
    *,
    verify_expiry: bool = True,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> dict:
    """Fetch the session descriptor from the runtime and validate it.

    Phases and their ConnectError codes:
      1. DNS + TCP connect         → TUNNEL_FAILED
      2. TLS handshake             → TUNNEL_FAILED (SSL error)
      3. HTTP GET /tek/descriptor  → TIMEOUT / AUTH_FAILED / NOT_READY / HTTP_ERROR
      4. Parse + validate          → DESCRIPTOR_ERROR / AUTH_FAILED
    """
    token = descriptor_token(secret)
    url   = f"https://{host}/tek/descriptor"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            # Explicitly request HTTP/1.1 keep-alive semantics.
            # Cloudflare respects Connection: close and won't reuse the socket.
            "Connection":    "close",
        },
    )

    # Custom opener forces HTTP/1.1 ALPN — fixes BUG B.
    ssl_ctx = _make_ssl_context()
    opener  = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_ctx)
    )

    try:
        with opener.open(req, timeout=timeout_s) as resp:
            raw = resp.read().decode()

    except socket.timeout:
        raise ConnectError(
            "TIMEOUT",
            f"The runtime did not respond within {timeout_s} s. "
            "The tunnel may still be starting — wait 10 seconds and retry.",
        )
    except TimeoutError:
        # On Python 3.11+, socket.timeout is an alias for TimeoutError
        raise ConnectError(
            "TIMEOUT",
            f"Connection timed out after {timeout_s} s. Try again in a moment.",
        )
    except ssl.SSLError as exc:
        raise ConnectError(
            "TUNNEL_FAILED",
            f"TLS error connecting to {host}: {exc.reason}. "
            "Check that the tunnel hostname is correct.",
        )
    except urllib.error.HTTPError as exc:
        body, code = "", "HTTP_ERROR"
        try:
            body = exc.read().decode()
            code = json.loads(body).get("code", "HTTP_ERROR")
        except Exception:
            pass
        if exc.code == 503:
            raise ConnectError(
                "NOT_READY",
                "Runtime is still initializing (503). "
                "Wait a few seconds and retry.",
            )
        if exc.code == 401:
            raise ConnectError(
                "AUTH_FAILED",
                "Authentication failed (401). "
                "Ensure the secret in the controller matches TEK_SESSION_SECRET "
                "set in the Kaggle notebook.",
            )
        raise ConnectError(code, f"HTTP {exc.code}: {body[:300]}") from exc

    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        raise ConnectError(
            "TUNNEL_FAILED",
            f"Could not reach {host}: {reason}. "
            "Verify the tunnel hostname and that the Kaggle notebook is running.",
        ) from exc

    except OSError as exc:
        raise ConnectError(
            "TUNNEL_FAILED",
            f"Network error: {exc}.",
        ) from exc

    # Parse and validate the descriptor
    try:
        desc = parse_descriptor(raw, check_expiry=verify_expiry)
    except DescriptorError as exc:
        raise ConnectError("DESCRIPTOR_ERROR", str(exc)) from exc

    # Verify that the runtime is using the same secret
    expected_fp = fingerprint(secret)
    actual_fp   = desc.get("secret_fingerprint", "")
    if actual_fp != expected_fp:
        raise ConnectError(
            "AUTH_FAILED",
            "Secret fingerprint mismatch. "
            "The runtime is not using the same TEK_SESSION_SECRET. "
            f"Expected {expected_fp}, got {actual_fp}.",
        )

    return desc


def build_kickoff_url(secret: bytes, host: str) -> str:
    """URL that sets the session cookie and redirects to /vnc.html."""
    from .crypto import kickoff_token as _kt
    return f"https://{host}/tek/kickoff?t={_kt(secret)}"


def fetch_with_retry(
    secret: bytes,
    host: str,
    *,
    verify_expiry: bool = True,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    max_attempts: int = 5,
    base_backoff_s: float = 3.0,
    on_attempt: "Callable[[int, str], None] | None" = None,
) -> dict:
    """Retry fetch_descriptor with exponential backoff.

    Retries on TIMEOUT and NOT_READY (retryable errors).
    Raises immediately on AUTH_FAILED or DESCRIPTOR_ERROR (permanent errors).

    Parameters
    ----------
    on_attempt   Called with (attempt_number, status_message) before each retry.
    """
    from typing import Callable
    _RETRYABLE = {"TIMEOUT", "NOT_READY", "TUNNEL_FAILED"}
    last_exc: ConnectError | None = None

    for attempt in range(1, max_attempts + 1):
        if on_attempt:
            on_attempt(attempt, f"Attempt {attempt}/{max_attempts}…")
        try:
            return fetch_descriptor(secret, host,
                                    verify_expiry=verify_expiry,
                                    timeout_s=timeout_s)
        except ConnectError as exc:
            last_exc = exc
            if exc.code not in _RETRYABLE:
                raise  # permanent failure — do not retry
            if attempt < max_attempts:
                wait = min(base_backoff_s * (2 ** (attempt - 1)), 30.0)
                if on_attempt:
                    on_attempt(attempt, f"{exc.code}: {exc.message[:60]}… retrying in {wait:.0f}s")
                import time as _t
                _t.sleep(wait)

    raise last_exc  # type: ignore[misc]
