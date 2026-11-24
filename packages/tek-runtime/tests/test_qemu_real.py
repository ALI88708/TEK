"""INTEGRATION tests with a REAL qemu-system-x86_64 (TCG). No mocks.

These prove local behaviour of QEMU start / monitor / VNC / stop. They do NOT prove
anything about Kaggle (different kernel, no /dev/kvm, network, cgroup limits).
Skipped automatically when QEMU is not installed.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
import tek_runtime.qemu as q

pytestmark = pytest.mark.skipif(
    not shutil.which("qemu-system-x86_64"), reason="qemu-system-x86_64 not installed"
)
PW = "abcd1234"


@pytest.fixture
def iso(tmp_path):
    p = tmp_path / "blank.iso"
    p.write_bytes(b"\x00" * (2 * 1024 * 1024))   # not bootable: BIOS says "no bootable device"
    return str(p)


@pytest.fixture(autouse=True)
def fast_clean_stop():
    q._POWERDOWN_WAIT_S, q._SIGTERM_WAIT_S = 1, 5
    yield
    q.stop()
    assert shutil.which("pgrep")
    left = subprocess.run(["pgrep", "-x", "qemu-system-x86_64"], capture_output=True, text=True).stdout.split()
    for pid in left:           # safety net so one failing test can't poison the next
        os.kill(int(pid), 9)


def _rfb_banner(port: int) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
        s.settimeout(3)
        return s.recv(12)


def test_real_start_monitor_vnc_and_stop(iso):
    q.start(iso, 1, 256, PW)
    assert q.is_alive()
    assert "running" in (q.status() or "")
    port = q.get_vnc_port()
    assert port is not None and 5900 <= port <= 5910
    q.wait_vnc_ready(port)                          # real RFB handshake banner
    assert _rfb_banner(port).startswith(b"RFB ")
    pid = q.pid()
    q.stop()
    assert q._proc is None and q._log_fd is None
    assert not os.path.exists(q._MON_SOCK)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_real_vnc_port_discovery_when_5900_is_taken(iso):
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        blocker.bind(("127.0.0.1", 5900)); blocker.listen(1)
    except OSError:
        pytest.skip("port 5900 not bindable in this environment")
    try:
        q.start(iso, 1, 256, PW)
        port = q.get_vnc_port()
        assert port is not None and port != 5900, "QEMU must move to a free port"
        assert _rfb_banner(port).startswith(b"RFB ")
    finally:
        blocker.close()


def test_real_refuses_to_start_next_to_an_unmanaged_qemu(iso):
    orphan = subprocess.Popen(
        ["qemu-system-x86_64", "-display", "none", "-S", "-m", "64", "-monitor", "none"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        with pytest.raises(RuntimeError, match="not started by this session"):
            q.start(iso, 1, 256, PW)
        assert orphan.poll() is None, "TEK must NOT kill a process it does not own"
    finally:
        orphan.kill(); orphan.wait()


def test_real_start_with_qcow2_disk(iso, tmp_path):
    from tek_runtime.disk import DiskSpec, create, validate
    disk = create(DiskSpec(path=str(tmp_path / "d.qcow2"), size_gb=1))
    assert validate(disk)["format"] == "qcow2"
    q.start(iso, 1, 256, PW, disk_path=disk, boot_order="dc")
    assert q.is_alive()
    q.wait_vnc_ready(q.get_vnc_port())


@pytest.mark.skipif(q._find_ovmf() is None, reason="OVMF not installed")
def test_real_uefi_boot_starts(iso):
    q.start(iso, 1, 512, PW, firmware="uefi")
    assert q.is_alive()
    q.wait_vnc_ready(q.get_vnc_port())


def test_real_q35_machine_starts(iso):
    q.start(iso, 1, 256, PW, machine="q35")
    assert q.is_alive()


def test_real_proc_lookup_finds_long_program_name(iso):
    """Regression: `pgrep -x qemu-system-x86_64` never matched (comm is 15 chars)."""
    from tek_runtime.procs import pids_by_name
    q.start(iso, 1, 256, PW)
    assert q.pid() in pids_by_name("qemu-system-x86_64")


def test_real_metrics_report_qemu_running(iso):
    """Regression for the Update-7 Control Panel bug (QEMU always shown as stopped)."""
    from tek_runtime.metrics import process_list
    assert {p["name"]: p["running"] for p in process_list()}["qemu-system-x86_64"] is False
    q.start(iso, 1, 256, PW)
    assert {p["name"]: p["running"] for p in process_list()}["qemu-system-x86_64"] is True


def test_real_qmp_socket_is_private(iso):
    q.start(iso, 1, 256, PW)
    mode = os.stat(os.path.dirname(q._MON_SOCK)).st_mode & 0o777
    assert mode == 0o700, f"QMP socket dir must be 0700, got {oct(mode)}"
    sock_dir = os.path.dirname(q._MON_SOCK)
    q.stop()
    assert not os.path.exists(sock_dir), "private socket dir must be removed on stop"


def test_real_qmp_error_is_reported_not_swallowed(iso):
    q.start(iso, 1, 256, PW)
    with pytest.raises(q.QmpError):
        q._qmp("this-command-does-not-exist")
