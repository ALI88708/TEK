"""QEMU lifecycle — generic, OS-agnostic VM manager.

Design:
  - Accepts explicit vcpu/ram/firmware/machine/boot_order/extra_args.
  - No hard-coded OS assumptions.
  - Supports BIOS (default) and UEFI (requires OVMF).
  - VNC discovery: uses `:0,to=10` so QEMU auto-selects a free port in 5900-5910.
  - Stop escalation: system_powerdown → SIGTERM → SIGKILL.
  - Log file: stdout/stderr → _QEMU_LOG (never to notebook output).
  - VNC password: set via monitor, never logged.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from typing import IO

from .procs import pids_by_name

# QMP (JSON) control socket. start() puts it inside a private 0700 directory so
# other local users cannot connect to it.
_MON_SOCK = "/tmp/tek-qemu-qmp.sock"
_MON_DIR: str | None = None
_QEMU_LOG  = os.path.join(tempfile.gettempdir(), "tek-qemu.log")
_VNC_BASE  = 5900          # VNC display :0 = port 5900

_proc:   subprocess.Popen | None = None
_log_fd: IO[str]           | None = None


# ======================================================================
# UEFI firmware discovery
# ======================================================================

_OVMF_PATHS = [
    "/usr/share/OVMF/OVMF_CODE.fd",
    "/usr/share/ovmf/OVMF.fd",
    "/usr/share/edk2/ovmf/OVMF_CODE.fd",
    "/usr/share/OVMF/x64/OVMF_CODE.fd",
]


def _find_ovmf() -> str | None:
    for p in _OVMF_PATHS:
        if os.path.isfile(p):
            return p
    return None


def ensure_uefi_firmware() -> str:
    """Return path to OVMF firmware, installing it if needed.

    Raises RuntimeError if OVMF cannot be installed.
    """
    path = _find_ovmf()
    if path:
        return path
    # Try to install
    result = subprocess.run(
        ["apt-get", "-qq", "install", "-y", "ovmf"],
        capture_output=True, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    if result.returncode != 0:
        raise RuntimeError(
            "UEFI firmware (OVMF) could not be installed. "
            "Install it manually: apt-get install ovmf"
        )
    path = _find_ovmf()
    if not path:
        raise RuntimeError(
            "OVMF installed but firmware file not found. "
            f"Searched: {_OVMF_PATHS}"
        )
    return path


# ======================================================================
# Monitor helpers
# ======================================================================

class QmpError(RuntimeError):
    """A QMP command failed, timed out, or the socket is unusable."""


def _qmp(execute: str, arguments: dict | None = None, timeout: float = 5.0):
    """Run one QMP command on a fresh connection and return its `return` value."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(_MON_SOCK)
        f = s.makefile("rw", encoding="utf-8", newline="\n")

        def send(cmd: dict) -> None:
            f.write(json.dumps(cmd) + "\n")
            f.flush()

        def reply():
            while True:
                line = f.readline()
                if not line:
                    raise QmpError(f"QMP connection closed during {execute!r}")
                msg = json.loads(line)
                if "return" in msg:
                    return msg["return"]
                if "error" in msg:
                    raise QmpError(str(msg["error"].get("desc", "QMP error")))
                # otherwise: an asynchronous event, ignore it

        if "QMP" not in json.loads(f.readline() or "{}"):
            raise QmpError("unexpected QMP greeting")
        send({"execute": "qmp_capabilities"})
        reply()
        cmd: dict = {"execute": execute}
        if arguments:
            cmd["arguments"] = arguments
        send(cmd)
        return reply()
    except socket.timeout as exc:
        raise QmpError(f"QMP timeout during {execute!r}") from exc
    except (OSError, ValueError) as exc:
        raise QmpError(f"QMP communication error during {execute!r}: {exc}") from exc
    finally:
        s.close()


def _set_vnc_password(password: str) -> None:
    """Set the VNC password. The password never appears in any error message."""
    try:
        _qmp("set_password", {"protocol": "vnc", "password": password})
    except QmpError as exc:
        raise RuntimeError(
            "QEMU did not accept the VNC password: " + str(exc).replace(password, "<redacted>")
        ) from None


def get_vnc_port() -> int | None:
    """The VNC port QEMU actually bound (query-vnc). None if it cannot be determined."""
    try:
        info = _qmp("query-vnc")
    except QmpError:
        return None
    service = str(info.get("service", ""))
    return int(service) if info.get("enabled") and service.isdigit() else None


def wait_vnc_ready(port: int, timeout: float = 15.0) -> None:
    """Block until a real VNC server answers on `port` (RFB banner), else raise."""
    deadline = time.time() + timeout
    last = "no connection"
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as s:
                s.settimeout(1.0)
                banner = s.recv(12)
                if banner.startswith(b"RFB "):
                    return
                last = f"unexpected banner {banner[:12]!r}"
        except OSError as exc:
            last = str(exc)
        time.sleep(0.3)
    raise RuntimeError(f"No VNC server answered on 127.0.0.1:{port} ({last}).")


def foreign_qemu_pids() -> list[int]:
    """PIDs of qemu-system-x86_64 processes that this module did not start."""
    mine = _proc.pid if _proc is not None else None
    return [p for p in pids_by_name("qemu-system-x86_64") if p != mine]


def _read_log_tail(n: int = 20) -> str:
    try:
        return "".join(open(_QEMU_LOG).readlines()[-n:])
    except OSError:
        return ""


# ======================================================================
# Start
# ======================================================================

def start(
    iso_path:   str,
    vcpu:       int,
    ram_mb:     int,
    vnc_password: str,
    *,
    disk_path:    str | None = None,
    machine:      str        = "pc",
    boot_order:   str        = "d",
    firmware:     str        = "bios",
    extra_args:   list[str] | None = None,
) -> None:
    """Start QEMU as a tracked child process.

    Parameters
    ----------
    iso_path      Path to the CD-ROM ISO.
    vcpu          Virtual CPU count.
    ram_mb        Guest RAM in MB.
    vnc_password  Derived from session secret — never logged.
    disk_path     Optional QCOW2 persistent disk.
    machine       "pc" (i440FX) or "q35" (ICH9/Windows).
    boot_order    QEMU -boot argument ("d", "c", "dc", ...).
    firmware      "bios" or "uefi".
    extra_args    Additional raw QEMU arguments.
    """
    global _proc, _log_fd

    if _proc is not None and _proc.poll() is None:
        raise RuntimeError("QEMU is already running. Call stop() first.")

    foreign = foreign_qemu_pids()
    if foreign:
        raise RuntimeError(
            f"Another qemu-system-x86_64 process is already running (PID {foreign[0]}) "
            "and was not started by this session (orphan from an earlier run?). "
            "TEK will not kill processes it does not own. "
            "Stop it yourself (e.g. !pkill -x qemu-system-x86_64) and retry."
        )

    global _MON_SOCK, _MON_DIR
    _cleanup_socket()
    _MON_DIR = tempfile.mkdtemp(prefix="tek-qmp-")          # mode 0700
    _MON_SOCK = os.path.join(_MON_DIR, "qmp.sock")

    cmd = [
        "qemu-system-x86_64",
        "-accel",   "tcg,thread=multi",
        "-cpu",     "max",
        "-machine", machine,
        "-smp",     str(vcpu),
        "-m",       str(ram_mb),
        "-vga",     "std",
        "-vnc",     "127.0.0.1:0,to=10,password=on",
        "-qmp",     f"unix:{_MON_SOCK},server=on,wait=off",
    ]

    # Firmware
    if firmware == "uefi":
        ovmf = ensure_uefi_firmware()
        cmd += ["-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={ovmf}"]

    # CD-ROM + boot
    if iso_path:
        cmd += ["-cdrom", iso_path, "-boot", boot_order]

    # Persistent disk
    if disk_path:
        cmd += ["-drive", f"file={disk_path},format=qcow2,if=virtio"]

    # Extra OS-specific args
    if extra_args:
        cmd += extra_args

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

    # Wait for monitor socket
    for _ in range(40):
        if os.path.exists(_MON_SOCK):
            break
        if _proc.poll() is not None:
            tail = _read_log_tail()
            _cleanup_all()
            raise RuntimeError(
                f"QEMU exited (code {_proc.returncode}).\n{tail}"
            )
        time.sleep(0.5)
    else:
        _force_kill("monitor socket never appeared")
        raise RuntimeError("QEMU monitor socket did not appear within 20 s.")

    _set_vnc_password(vnc_password)


# ======================================================================
# Status helpers
# ======================================================================

def pid() -> int | None:
    return _proc.pid if _proc else None


def status() -> str | None:
    """QEMU run state ("running", "paused", ...) or None if QMP is unreachable."""
    try:
        return str(_qmp("query-status").get("status"))
    except QmpError:
        return None


def is_alive() -> bool:
    if _proc is None or _proc.poll() is not None:
        return False
    return status() is not None


def screenshot(path: str) -> bool:
    try:
        _qmp("screendump", {"filename": path})
        return os.path.exists(path)
    except QmpError:
        return False


# ======================================================================
# Stop with escalation
# ======================================================================

_POWERDOWN_WAIT_S = 15
_SIGTERM_WAIT_S   = 8
_SIGKILL_WAIT_S   = 5


def stop() -> None:
    global _proc
    if _proc is None:
        _cleanup_all()
        return
    try:
        _qmp("system_powerdown")
    except QmpError:
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
    global _proc
    if _proc is None:
        return
    _safe_signal(_proc, signal.SIGKILL)
    try:
        _proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    print(f"WARNING: QEMU force-killed: {reason}")
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
    global _proc, _log_fd
    if _log_fd is not None:
        try:
            _log_fd.close()
        except Exception:
            pass
        _log_fd = None
    _proc = None
    _cleanup_socket()


def _cleanup_socket() -> None:
    global _MON_DIR
    try:
        if os.path.exists(_MON_SOCK):
            os.remove(_MON_SOCK)
    except OSError:
        pass
    if _MON_DIR:
        shutil.rmtree(_MON_DIR, ignore_errors=True)
        _MON_DIR = None
