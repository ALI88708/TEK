"""Start websockify: VNC → WebSocket bridge on loopback.

Idempotent: if websockify is already listening on the port (e.g. notebook
cell re-run), start() returns immediately without spawning a second instance.
"""
from __future__ import annotations

import socket
import subprocess
import time

_WEBSOCKIFY_PORT = 6081
_VNC_PORT        = 5900
_proc: subprocess.Popen | None = None


def _port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _WEBSOCKIFY_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def start() -> None:
    global _proc

    # Already running in this process
    if _proc is not None and _proc.poll() is None:
        return

    # Port already in use by an external process (e.g. previous kernel run)
    if _port_open():
        print("  websockify already listening on port 6081 — reusing.")
        return

    _proc = subprocess.Popen(
        ["websockify", str(_WEBSOCKIFY_PORT), f"127.0.0.1:{_VNC_PORT}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(20):
        time.sleep(0.3)
        if _proc.poll() is not None:
            raise RuntimeError(
                f"websockify exited immediately (code {_proc.returncode})."
            )
        if _port_open():
            return

    raise RuntimeError("websockify did not open port 6081 within 6 s.")


def stop() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
            _proc.wait(timeout=3)
    _proc = None
