"""Start websockify: VNC → WebSocket bridge on loopback."""
from __future__ import annotations

import subprocess
import time

_WEBSOCKIFY_PORT = 6081
_VNC_PORT = 5900
_proc: subprocess.Popen | None = None


def start() -> None:
    global _proc
    _proc = subprocess.Popen(
        ["websockify", str(_WEBSOCKIFY_PORT), f"127.0.0.1:{_VNC_PORT}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give it a moment; it doesn't serve plain HTTP so we just wait.
    for _ in range(20):
        time.sleep(0.3)
        if _proc.poll() is not None:
            raise RuntimeError("websockify exited immediately.")
        # Port open check
        import socket
        try:
            with socket.create_connection(("127.0.0.1", _WEBSOCKIFY_PORT), timeout=0.5):
                return
        except OSError:
            pass
    raise RuntimeError("websockify did not open its port within 6 s.")


def stop() -> None:
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except Exception:
            _proc.kill()
