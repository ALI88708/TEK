"""QEMU lifecycle: start, monitor, graceful stop with escalation.

Design decisions:
1.  No -daemonize — Popen() keeps the PID in our control.
2.  Stop escalation: system_powerdown → SIGTERM → SIGKILL, each verified.
3.  QEMU output is redirected to a log file (_QEMU_LOG), never to stdout.
    The log file handle is stored at module level and closed in _cleanup().
4.  VNC password is set through the monitor after startup. The monitor
    response is checked; the password is never included in any exception
    message or log line.
5.  The module keeps a single global _proc / _log_fd pair.
    Calling start() while already running is an error.
"""
from __future__ import annotations

import io
import os
import signal
import socket
import subprocess
import time
from typing import IO

_MON_SOCK = "/tmp/tek-qemu-mon.sock"
_QEMU_LOG = "/tmp/tek-qemu.log"

_proc:   subprocess.Popen | None = None
_log_fd: IO[str]          | None = None   # held open while QEMU runs


# ======================================================================
# Monitor helpers
# ======================================================================

def _mon(cmd: str, timeout: float = 5.0) -> str:
    """Send one HMP command and return the raw response string."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(_MON_SOCK)
        s.sendall((cmd + "\n").encode())
        time.sleep(0.25)
        try:
            data = s.recv(65536).decode(errors="replace")
        except socket.timeout:
            data = ""
        return data.strip()
    finally:
        s.close()


def _set_vnc_password(password: str) -> None:
    """Set the VNC session password via the HMP monitor.

    Raises RuntimeError on timeout or monitor error.
    The password is NEVER included in any exception message or log output.
    """
    try:
        response = _mon(f"change vnc password {password}")
    except Exception as exc:
        raise RuntimeError(
            "QEMU monitor did not accept the VNC password command "
            "(communication error)."
        ) from exc

    if not response:
        # socket.timeout inside _mon returns "" — we cannot confirm success
        raise RuntimeError(
            "QEMU monitor did not respond to the VNC password command (timeout). "
            "The password may not have been set."
        )

    # HMP reports errors on a line starting with or containing "Error"
    lower = response.lower()
    if "error" in lower or "invalid" in lower:
        # Strip the password from the response before surfacing it
        safe = response.replace(password, "<redacted>")
        raise RuntimeError(
            f"QEMU monitor returned an error while setting VNC password: {safe}"
        )


def _read_log_tail(n: int = 20) -> str:
    try:
        lines = open(_QEMU_LOG).readlines()
        return "".join(lines[-n:])
    except OSError:
        return ""


# ======================================================================
# Start
# ======================================================================

def start(
    iso_path: str,
    vcpu: int,
    ram_mb: int,
    vnc_password: str,
    disk_path: str | None = None,
) -> None:
    """Start QEMU as a tracked child process. Raises if already running."""
    global _proc, _log_fd

    if _proc is not None and _proc.poll() is None:
        raise RuntimeError("QEMU is already running. Call stop() first.")

    if os.path.exists(_MON_SOCK):
        os.remove(_MON_SOCK)

    cmd = [
        "qemu-system-x86_64",
        "-accel", "tcg,thread=multi",
        "-cpu",   "max",
        "-smp",   str(vcpu),
        "-m",     str(ram_mb),
        "-cdrom", iso_path,
        "-boot",  "d",
        "-vga",   "std",
        "-vnc",   "127.0.0.1:0,password=on",
        "-monitor", f"unix:{_MON_SOCK},server,nowait",
        # No -daemonize: keep the Popen handle for safe shutdown.
    ]
    if disk_path:
        cmd += ["-drive", f"file={disk_path},format=qcow2,if=virtio"]

    # Open log file before Popen so we can close it if Popen raises.
    _log_fd = open(_QEMU_LOG, "w")
    try:
        _proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=_log_fd,
            stderr=_log_fd,
        )
    except Exception:
        _log_fd.close()
        _log_fd = None
        raise

    # Wait for monitor socket (up to 20 s)
    for _ in range(40):
        if os.path.exists(_MON_SOCK):
            break
        if _proc.poll() is not None:
            tail = _read_log_tail()
            _cleanup_all()
            raise RuntimeError(
                f"QEMU exited prematurely (code {_proc.returncode}).\n{tail}"
            )
        time.sleep(0.5)
    else:
        _force_kill("monitor socket never appeared")
        raise RuntimeError("QEMU monitor socket did not appear within 20 s.")

    # Set VNC password and verify the monitor accepted it.
    # Raises RuntimeError if the monitor returns an error or times out.
    _set_vnc_password(vnc_password)


# ======================================================================
# Status helpers
# ======================================================================

def pid() -> int | None:
    return _proc.pid if _proc is not None else None


def status() -> str | None:
    try:
        out = _mon("info status")
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def is_alive() -> bool:
    if _proc is None or _proc.poll() is not None:
        return False
    return status() is not None


def screenshot(path: str) -> bool:
    try:
        _mon(f"screendump {path}")
        return os.path.exists(path)
    except Exception:
        return False


# ======================================================================
# Stop with escalation
# ======================================================================

_POWERDOWN_WAIT_S = 15
_SIGTERM_WAIT_S   = 8
_SIGKILL_WAIT_S   = 5


def stop() -> None:
    """Gracefully stop QEMU with safe escalation.

    Steps:
      1. system_powerdown (ACPI) — waits _POWERDOWN_WAIT_S s.
      2. SIGTERM               — waits _SIGTERM_WAIT_S s.
      3. SIGKILL               — waits _SIGKILL_WAIT_S s.
      4. Warning if still alive (process state is unresolved).
    Each step is skipped if the process has already exited.
    """
    global _proc

    if _proc is None:
        _cleanup_all()
        return

    try:
        _mon("system_powerdown")
    except Exception:
        pass

    if _wait_for_exit(_POWERDOWN_WAIT_S):
        _cleanup_all()
        return

    _safe_signal(_proc, signal.SIGTERM)
    if _wait_for_exit(_SIGTERM_WAIT_S):
        _cleanup_all()
        return

    _safe_signal(_proc, signal.SIGKILL)
    if _wait_for_exit(_SIGKILL_WAIT_S):
        _cleanup_all()
        return

    print(
        f"WARNING: QEMU (PID {_proc.pid}) did not exit after SIGKILL. "
        "Manual intervention required."
    )
    _cleanup_all()


# ======================================================================
# Internal helpers
# ======================================================================

def _force_kill(reason: str) -> None:
    """SIGKILL without escalation — used when startup fails."""
    global _proc
    if _proc is None:
        return
    _safe_signal(_proc, signal.SIGKILL)
    try:
        _proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    print(f"WARNING: QEMU force-killed during startup: {reason}")
    _cleanup_all()


def _wait_for_exit(seconds: float) -> bool:
    if _proc is None:
        return True
    try:
        _proc.wait(timeout=seconds)
        return True
    except subprocess.TimeoutExpired:
        return False


def _safe_signal(proc: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        if proc.poll() is None:
            os.kill(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _cleanup_all() -> None:
    """Close the log file, clear the process handle, remove the socket."""
    global _proc, _log_fd
    # Close log file only after the process has exited (or been killed).
    if _log_fd is not None:
        try:
            _log_fd.close()
        except Exception:
            pass
        _log_fd = None
    _proc = None
    _cleanup_socket()


def _cleanup_socket() -> None:
    if os.path.exists(_MON_SOCK):
        try:
            os.remove(_MON_SOCK)
        except OSError:
            pass
