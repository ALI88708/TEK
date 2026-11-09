"""Build and serve the session descriptor. Enforce output invariants."""
from __future__ import annotations

import json
import random
import string
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

_SESSION_ALPHABET = string.ascii_uppercase + string.digits
_DEFAULT_TTL = 43200  # 12 h


def _session_id() -> str:
    return "s_" + "".join(random.choices(_SESSION_ALPHABET, k=10))


def make_descriptor(
    secret: bytes,
    tunnel_url: str,
    plan_dict: dict,
    *,
    guest_os: str = "alpine",
    guest_state: str = "ready",
    runtime_version: str = "0.1.0",
    ttl: int = _DEFAULT_TTL,
) -> tuple[str, str]:
    """Return (session_id, descriptor_json).

    Imports crypto lazily to keep this module importable without the full package.
    """
    from .crypto import fingerprint

    now = time.time()
    sid = _session_id()
    host = urlsplit(tunnel_url).hostname or tunnel_url

    created = datetime.fromtimestamp(now, tz=timezone.utc)
    expires = datetime.fromtimestamp(now + ttl, tz=timezone.utc)

    desc = {
        "schema": "tek.session.v0",
        "protocol": "tek/0",
        "session_id": sid,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime_version": runtime_version,
        "secret_fingerprint": fingerprint(secret),
        "display": {
            "transport": "vnc",
            "url": f"https://{host}/vnc.html",
            "password_scheme": "hkdf-sha256/v1",
            "geometry": [1280, 800],
        },
        "resources": plan_dict,
        "guest": {
            "os": guest_os,
            "state": guest_state,
        },
    }
    return sid, json.dumps(desc, indent=2)
