"""Fetch and validate the session descriptor from the live runtime.

Flow:
  1. Derive descriptor_token from the secret.
  2. GET https://<host>/tek/descriptor  Authorization: Bearer <token>
  3. Parse descriptor, verify fingerprint and protocol.
  4. Return the validated descriptor dict.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .crypto import descriptor_token, fingerprint, pairing_nonce
from .descriptor import DescriptorError, parse_descriptor


class ConnectError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fetch_descriptor(secret: bytes, host: str, *, verify_expiry: bool = True) -> dict:
    """Fetch the descriptor from the runtime and return the validated dict.

    Raises ConnectError on any auth, network, or validation failure.
    """
    token = descriptor_token(secret)
    url = f"https://{host}/tek/descriptor"

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()
            data = json.loads(body)
            code = data.get("code", "AUTH_FAILED")
        except Exception:
            code = "AUTH_FAILED"
        raise ConnectError(code, f"HTTP {exc.code} from runtime: {body[:200]}") from exc
    except urllib.error.URLError as exc:
        raise ConnectError(
            "TUNNEL_FAILED", f"Could not reach {host}: {exc.reason}"
        ) from exc

    try:
        desc = parse_descriptor(raw, check_expiry=verify_expiry)
    except DescriptorError as exc:
        raise ConnectError(exc.code, str(exc)) from exc

    # Fingerprint check: confirms both sides hold the same secret
    expected_fp = fingerprint(secret)
    if desc.get("secret_fingerprint") != expected_fp:
        raise ConnectError(
            "AUTH_FAILED",
            "Secret fingerprint mismatch. "
            "The runtime does not hold the same session secret.",
        )

    return desc


def build_kickoff_url(secret: bytes, host: str) -> str:
    """URL that issues the session cookie and redirects to /vnc.html."""
    from .crypto import kickoff_token as _kt
    return f"https://{host}/tek/kickoff?t={_kt(secret)}"
