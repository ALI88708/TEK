"""Cryptographic derivations for TEK protocol v0.

All secrets stay in memory. Nothing here logs, prints, or persists a secret,
auth token, VNC password, or cookie value.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import math
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

_SALT = b"tek/v0"


# ---------- primitives --------------------------------------------------

def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256 (RFC 5869). Single or multi-block expand."""
    prk = _hmac.new(salt, ikm, hashlib.sha256).digest()
    t, out = b"", b""
    for i in range(1, math.ceil(length / 32) + 1):
        t = _hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
    return out[:length]


def b64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    pad = 4 - len(text) % 4
    return urlsafe_b64decode(text + "=" * (pad % 4))


# ---------- secret lifecycle --------------------------------------------

def generate_secret() -> bytes:
    """32-byte CSPRNG secret. Call once per session."""
    return secrets.token_bytes(32)


def secret_from_env(env_value: str) -> bytes:
    """Parse the base64url secret from TEK_SESSION_SECRET."""
    raw = env_value.strip()
    if not raw:
        raise ValueError("TEK_SESSION_SECRET is empty.")
    data = b64url_decode(raw)
    if len(data) != 32:
        raise ValueError(
            f"TEK_SESSION_SECRET must decode to 32 bytes; got {len(data)}."
        )
    return data


# ---------- derived credentials -----------------------------------------

def auth_token(secret: bytes, w: int | None = None) -> str:
    """Short-lived display credential. w = floor(unix_time / 300)."""
    if w is None:
        w = int(time.time()) // 300
    info = b"tek/v0/auth/" + str(w).encode()
    return b64url_encode(_hkdf_sha256(secret, _SALT, info, 32))


def descriptor_token(secret: bytes) -> str:
    """One-shot credential for GET /tek/descriptor."""
    return b64url_encode(_hkdf_sha256(secret, _SALT, b"tek/v0/descriptor", 32))


def vnc_password(secret: bytes) -> str:
    """8-character VNC password (second factor only, never the auth boundary)."""
    return b64url_encode(_hkdf_sha256(secret, _SALT, b"tek/v0/vnc", 6))[:8]


def fingerprint(secret: bytes) -> str:
    """8 hex characters for human verification of the shared secret."""
    return hashlib.sha256(secret).digest()[:4].hex()


def pairing_nonce(secret: bytes) -> str:
    """6-character human-visible check. Not an authentication credential."""
    return b64url_encode(_hkdf_sha256(secret, _SALT, b"tek/v0/pair", 4))[:6]


def kickoff_token(secret: bytes) -> str:
    """One-shot URL token for the browser kickoff endpoint."""
    return b64url_encode(_hkdf_sha256(secret, _SALT, b"tek/v0/kickoff", 32))


# ---------- cookie -------------------------------------------------------

_COOKIE_SIG_LEN = 16  # hex characters of HMAC-SHA256


def make_cookie_value(secret: bytes, session_id: str, expiry_unix: int) -> str:
    msg = f"{expiry_unix}:{session_id}".encode()
    sig = _hmac.new(secret, msg, hashlib.sha256).hexdigest()[:_COOKIE_SIG_LEN]
    return f"{expiry_unix}.{session_id}.{sig}"


def verify_cookie_value(
    secret: bytes, session_id: str, cookie: str, now: float | None = None
) -> bool:
    try:
        parts = cookie.split(".")
        if len(parts) != 3:
            return False
        expiry, sid, sig = int(parts[0]), parts[1], parts[2]
        if sid != session_id:
            return False
        if (now or time.time()) > expiry:
            return False
        msg = f"{expiry}:{session_id}".encode()
        expected = _hmac.new(secret, msg, hashlib.sha256).hexdigest()[:_COOKIE_SIG_LEN]
        return _hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ---------- token verification ------------------------------------------

def verify_auth_token(secret: bytes, token: str, now: float | None = None) -> bool:
    """Accept w-1, w, w+1 to allow ±5 min clock skew."""
    w = int(now or time.time()) // 300
    for window in (w - 1, w, w + 1):
        if _hmac.compare_digest(token, auth_token(secret, window)):
            return True
    return False


def verify_descriptor_token(secret: bytes, token: str) -> bool:
    return _hmac.compare_digest(token, descriptor_token(secret))


def verify_kickoff_token(secret: bytes, token: str) -> bool:
    return _hmac.compare_digest(token, kickoff_token(secret))


def relay_token(secret: bytes) -> str:
    """frp authentication token derived from session secret."""
    return b64url_encode(_hkdf_sha256(secret, _SALT, b"tek/v0/relay", 32))
