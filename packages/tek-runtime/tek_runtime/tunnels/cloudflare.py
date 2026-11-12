"""Cloudflare Quick Tunnel backend (wraps existing tunnel.py)."""
from __future__ import annotations
from .. import tunnel as _cf
from .base import TunnelBackend, TunnelResult
from urllib.parse import urlsplit


class CloudflareTunnel(TunnelBackend):
    """Cloudflare Quick Tunnel — no account required."""

    def __init__(self, timeout: int = 90) -> None:
        self._timeout = timeout
        self._url     = ""

    def start(self) -> TunnelResult:
        self._url = _cf.start(timeout=self._timeout)
        parsed    = urlsplit(self._url)
        return TunnelResult(
            public_url=self._url,
            host=parsed.hostname or "",
            port=443,
            is_relay=False,
        )

    def stop(self) -> None:
        _cf.stop()
        self._url = ""

    def is_alive(self) -> bool:
        return _cf._proc is not None and _cf._proc.poll() is None
