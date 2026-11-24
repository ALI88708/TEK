"""websockify: VNC -> WebSocket bridge on loopback.

The VNC port is NOT assumed to be 5900. QEMU is started with `:0,to=10`, so it may
pick any port in 5900-5910; the session reads the real port from the QEMU monitor
and passes it here. The port is remembered so the watchdog can restart the bridge
against the same VNC port.

If something that we did not start is already listening on the websockify port, we
refuse to reuse it: a stale websockify from a previous kernel could point at a dead
VNC port and silently show nothing.
"""
from __future__ import annotations

import socket
import subprocess
import time

_WEBSOCKIFY_PORT = 6081
_DEFAULT_VNC_PORT = 5900

_proc: subprocess.Popen | None = None
_vnc_port: int = _DEFAULT_VNC_PORT


def _port_open(port: int = _WEBSOCKIFY_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def current_vnc_port() -> int:
    return _vnc_port


def start(vnc_port: int | None = None) -> None:
    """Start websockify pointing at `vnc_port` (or the last used one)."""
    global _proc, _vnc_port
    if vnc_port is not None:
        _vnc_port = vnc_port

    if _proc is not None and _proc.poll() is None:
        return  # ours and alive (idempotent re-run)

    if _port_open():
        raise RuntimeError(
            f"Port {_WEBSOCKIFY_PORT} is already in use by a process TEK did not "
            "start (probably an orphan websockify from a previous run). "
            "Stop it first, e.g. in a notebook cell: !pkill -x websockify"
        )

    _proc = subprocess.Popen(
        ["websockify", str(_WEBSOCKIFY_PORT), f"127.0.0.1:{_vnc_port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(0.3)
        if _proc.poll() is not None:
            raise RuntimeError(f"websockify exited immediately (code {_proc.returncode}).")
        if _port_open():
            return
    raise RuntimeError(f"websockify did not open port {_WEBSOCKIFY_PORT} within 6 s.")


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
