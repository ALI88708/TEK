"""Unit tests for qemu.py stop escalation and resource cleanup.

These tests use real subprocess calls (sleep) so OS signals are exercised.
Nothing here starts a real QEMU binary.
Tests that require QEMU/Kaggle are marked NOT_RUN.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
import tek_runtime.qemu as Q


@pytest.fixture(autouse=True)
def reset_module():
    Q._proc   = None
    Q._log_fd = None
    yield
    if Q._proc is not None and Q._proc.poll() is None:
        try:
            os.kill(Q._proc.pid, signal.SIGKILL)
            Q._proc.wait(timeout=3)
        except Exception:
            pass
    if Q._log_fd is not None:
        try:
            Q._log_fd.close()
        except Exception:
            pass
    Q._proc   = None
    Q._log_fd = None


# ------------------------------------------------------------------ #
# _safe_signal                                                         #
# ------------------------------------------------------------------ #

def test_safe_signal_on_exited_process_does_not_raise():
    proc = subprocess.Popen(["true"], stdout=subprocess.DEVNULL)
    proc.wait()
    Q._safe_signal(proc, signal.SIGTERM)   # must not raise


def test_safe_signal_terminates_running_process():
    proc = subprocess.Popen(
        ["sleep", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    Q._safe_signal(proc, signal.SIGTERM)
    proc.wait(timeout=3)
    assert proc.poll() is not None


# ------------------------------------------------------------------ #
# _wait_for_exit                                                       #
# ------------------------------------------------------------------ #

def test_wait_for_exit_true_when_process_exits():
    Q._proc = subprocess.Popen(
        ["sleep", "0.05"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert Q._wait_for_exit(5) is True


def test_wait_for_exit_false_when_process_hangs():
    Q._proc = subprocess.Popen(
        ["sleep", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert Q._wait_for_exit(0.2) is False


def test_wait_for_exit_true_when_proc_none():
    Q._proc = None
    assert Q._wait_for_exit(1) is True


# ------------------------------------------------------------------ #
# _cleanup_all                                                         #
# ------------------------------------------------------------------ #

def test_cleanup_all_closes_log_fd():
    import tempfile
    fd = open(tempfile.mktemp(), "w")
    Q._log_fd = fd
    Q._proc   = None
    Q._cleanup_all()
    assert Q._log_fd is None
    assert fd.closed, "log_fd must be closed after _cleanup_all()"


def test_cleanup_all_clears_proc():
    Q._proc = subprocess.Popen(
        ["sleep", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = Q._proc.pid
    os.kill(pid, signal.SIGKILL)
    Q._proc.wait()
    Q._cleanup_all()
    assert Q._proc is None


# ------------------------------------------------------------------ #
# stop() — full flow with real processes                               #
# ------------------------------------------------------------------ #

def test_stop_safe_when_no_process():
    Q._proc   = None
    Q._log_fd = None
    Q.stop()   # must not raise


def test_stop_kills_process_responding_to_sigterm():
    Q._proc = subprocess.Popen(
        ["sleep", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = Q._proc.pid
    Q.stop()

    assert Q._proc is None
    time.sleep(0.1)
    try:
        os.kill(pid, 0)
        still_alive = True
    except ProcessLookupError:
        still_alive = False
    assert not still_alive, f"PID {pid} still alive after stop()"


def test_stop_clears_proc_and_log_fd():
    import tempfile
    Q._log_fd = open(tempfile.mktemp(), "w")
    Q._proc   = subprocess.Popen(
        ["sleep", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    fd = Q._log_fd
    Q.stop()

    assert Q._proc   is None
    assert Q._log_fd is None
    assert fd.closed


# ------------------------------------------------------------------ #
# _set_vnc_password  (unit — no QEMU)                                 #
# ------------------------------------------------------------------ #

def test_set_vnc_password_raises_on_empty_response(monkeypatch):
    """Empty monitor response (timeout) must raise, not silently succeed."""
    monkeypatch.setattr(Q, "_mon", lambda cmd, timeout=5.0: "")
    with pytest.raises(RuntimeError, match="did not respond"):
        Q._set_vnc_password("secret123")


def test_set_vnc_password_raises_on_error_response(monkeypatch):
    monkeypatch.setattr(Q, "_mon", lambda cmd, timeout=5.0: "Error: bad password")
    with pytest.raises(RuntimeError):
        Q._set_vnc_password("secret123")


def test_set_vnc_password_error_does_not_contain_password(monkeypatch):
    monkeypatch.setattr(Q, "_mon",
        lambda cmd, timeout=5.0: "Error: invalid parameter 'hunter2'")
    with pytest.raises(RuntimeError) as exc_info:
        Q._set_vnc_password("hunter2")
    assert "hunter2" not in str(exc_info.value), \
        "Password must not appear in the error message"


def test_set_vnc_password_ok_on_prompt_response(monkeypatch):
    """A response that contains only the monitor prompt is a success."""
    monkeypatch.setattr(Q, "_mon", lambda cmd, timeout=5.0: "(qemu)")
    Q._set_vnc_password("any_password")  # must not raise


def test_set_vnc_password_ok_on_empty_ok_response(monkeypatch):
    """Some QEMU versions return just a blank prompt — no 'error' keyword."""
    monkeypatch.setattr(Q, "_mon", lambda cmd, timeout=5.0: "\r\n(qemu) \r\n")
    Q._set_vnc_password("any_password")


# ------------------------------------------------------------------ #
# NOT_RUN markers                                                      #
# ------------------------------------------------------------------ #

@pytest.mark.skip(reason="NOT_RUN: requires QEMU binary and ISO on Kaggle")
def test_full_qemu_start_on_kaggle():
    pass

@pytest.mark.skip(reason="NOT_RUN: SIGKILL path requires process ignoring SIGTERM")
def test_sigkill_escalation_on_stubborn_process():
    pass
