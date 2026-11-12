"""HKDF derivations for the controller side — mirrors runtime/crypto.py.

The controller is the only side that holds the raw secret. It derives tokens
locally; nothing is fetched from the runtime that could expose the secret.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import math
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

_SALT = b"tek/v0"


def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = _hmac.new(salt, ikm, hashlib.sha256).digest()
    t, out = b"", b""
    for i in range(1, math.ceil(length / 32) + 1):
        t = _hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
    return out[:length]


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    pad = 4 - len(text) % 4
    return urlsafe_b64decode(text + "=" * (pad % 4))


def generate_secret() -> bytes:
    """32-byte CSPRNG secret for a new session."""
    return secrets.token_bytes(32)


def secret_to_str(secret: bytes) -> str:
    """Encode for display / copy in the UI (shown exactly once)."""
    return _b64url(secret)


def secret_from_str(text: str) -> bytes:
    data = _b64url_decode(text.strip())
    if len(data) != 32:
        raise ValueError(f"Secret must be 32 bytes; got {len(data)}.")
    return data


def auth_token(secret: bytes, w: int | None = None) -> str:
    if w is None:
        w = int(time.time()) // 300
    return _b64url(_hkdf_sha256(secret, _SALT, b"tek/v0/auth/" + str(w).encode(), 32))


def descriptor_token(secret: bytes) -> str:
    return _b64url(_hkdf_sha256(secret, _SALT, b"tek/v0/descriptor", 32))


def kickoff_token(secret: bytes) -> str:
    return _b64url(_hkdf_sha256(secret, _SALT, b"tek/v0/kickoff", 32))


def fingerprint(secret: bytes) -> str:
    return hashlib.sha256(secret).digest()[:4].hex()


def pairing_nonce(secret: bytes) -> str:
    return _b64url(_hkdf_sha256(secret, _SALT, b"tek/v0/pair", 4))[:6]


def relay_token(secret: bytes) -> str:
    """frp authentication token derived from session secret."""
    return _b64url(_hkdf_sha256(secret, _SALT, b"tek/v0/relay", 32))
