"""Fetch and validate the session descriptor from the live runtime.

Flow:
  1. Derive descriptor_token from the secret.
  2. GET https://<host>/tek/descriptor  Authorization: Bearer <token>
  3. Parse descriptor, verify fingerprint.
  4. Return the validated descriptor dict.

Error handling:
  - ConnectError with stable code is raised on every failure path.
  - Timeout: code=TIMEOUT, clear message so the UI shows something useful.
  - 503 NOT_READY: runtime is still starting — caller should retry.
  - Auth failure: code=AUTH_FAILED.
  - Network unreachable: code=TUNNEL_FAILED.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from .crypto import descriptor_token, fingerprint
from .descriptor import DescriptorError, parse_descriptor

_DEFAULT_TIMEOUT_S = 20


class ConnectError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message


def fetch_descriptor(
    secret: bytes,
    host: str,
    *,
    verify_expiry: bool = True,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> dict:
    """Fetch the descriptor and return the validated dict.

    Raises ConnectError on any failure.
    """
    token = descriptor_token(secret)
    url   = f"https://{host}/tek/descriptor"

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode()

    except socket.timeout:
        raise ConnectError(
            "TIMEOUT",
            f"The runtime did not respond within {timeout_s} s. "
            "The tunnel may still be starting — wait 10 seconds and retry.",
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
                "Runtime is still initializing. Wait a few seconds and retry.",
            )
        if exc.code == 401:
            raise ConnectError(
                "AUTH_FAILED",
                "Authentication failed. Ensure the secret matches TEK_SESSION_SECRET.",
            )
        raise ConnectError(code, f"HTTP {exc.code}: {body[:200]}") from exc

    except urllib.error.URLError as exc:
        raise ConnectError(
            "TUNNEL_FAILED",
            f"Could not reach {host}. "
            "Check that the tunnel hostname is correct and the runtime is running. "
            f"Detail: {exc.reason}",
        ) from exc

    try:
        desc = parse_descriptor(raw, check_expiry=verify_expiry)
    except DescriptorError as exc:
        raise ConnectError(exc.code, str(exc)) from exc

    expected_fp = fingerprint(secret)
    if desc.get("secret_fingerprint") != expected_fp:
        raise ConnectError(
            "AUTH_FAILED",
            "Secret fingerprint mismatch. "
            "The runtime is not using the same session secret.",
        )

    return desc


def build_kickoff_url(secret: bytes, host: str) -> str:
    """URL that sets the session cookie and redirects to /vnc.html."""
    from .crypto import kickoff_token as _kt
    return f"https://{host}/tek/kickoff?t={_kt(secret)}"
