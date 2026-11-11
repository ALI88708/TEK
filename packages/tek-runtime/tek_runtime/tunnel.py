"""Cloudflare quick tunnel: start (idempotent), parse URL, stop.

Idempotent: if the tunnel is already running and a URL is available in the
log, start() returns the existing URL without launching a second cloudflared.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

_LOG    = "/tmp/tek-cloudflared.log"
_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_proc: subprocess.Popen | None = None


def _try_parse_log() -> str | None:
    try:
        txt = open(_LOG, errors="replace").read()
        m   = _URL_RE.search(txt)
        return m.group(0) if m else None
    except OSError:
        return None


def _launch(extra_args: list[str] | None = None) -> None:
    global _proc
    if os.path.exists(_LOG):
        os.remove(_LOG)
    cmd = [
        "cloudflared", "tunnel",
        "--url", "http://127.0.0.1:6080",
        "--no-autoupdate",
        "--logfile", _LOG,
        *(extra_args or []),
    ]
    _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start(timeout: int = 90) -> str:
    """Start the tunnel and return its public HTTPS URL.

    Idempotent: returns the existing URL if the tunnel is already up.
    """
    global _proc

    # Reuse existing tunnel (same process)
    if _proc is not None and _proc.poll() is None:
        url = _try_parse_log()
        if url:
            print(f"  Tunnel already running: {url}")
            return url

    _launch()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        if _proc and _proc.poll() is not None:
            break  # crashed — retry with http2
        url = _try_parse_log()
        if url:
            return url

    # Retry once with explicit http2 protocol
    stop()
    _launch(["--protocol", "http2"])
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        url = _try_parse_log()
        if url:
            return url

    raise RuntimeError(
        "TUNNEL_FAILED: Cloudflare tunnel did not produce a URL. "
        "Check network connectivity and try again."
    )


def stop() -> None:
    global _proc
    if _proc:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except Exception:
            _proc.kill()
        _proc = None
