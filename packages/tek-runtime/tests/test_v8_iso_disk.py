"""Tests for Generic ISO Engine and Virtual Disk Management (v8)."""
from __future__ import annotations
import hashlib, os, sys, tempfile
import pytest
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
from tek_runtime.iso_manager import IsoSpec, prepare, IsoError
from tek_runtime.disk import DiskSpec, create as create_disk, validate, DiskError


# ======================================================================
# IsoSpec — constructor and factories
# ======================================================================

class TestIsoSpec:
    def test_path_factory(self):
        s = IsoSpec.from_path("/tmp/test.iso")
        assert s.path == "/tmp/test.iso"
        assert s.url == ""

    def test_url_factory(self):
        s = IsoSpec.from_url("https://example.com/os.iso")
        assert s.url == "https://example.com/os.iso"
        assert s.path == ""

    def test_alpine_shorthand(self):
        s = IsoSpec.alpine()
        assert s.url == "alpine"

    def test_display_name_from_path(self):
        s = IsoSpec.from_path("/tmp/ubuntu-24.04.iso")
        assert s.display_name == "ubuntu-24.04.iso"

    def test_display_name_explicit(self):
        s = IsoSpec.from_url("https://x.com/os.iso", name="Ubuntu 24.04")
        assert s.display_name == "Ubuntu 24.04"

    def test_requires_path_or_url(self):
        with pytest.raises(ValueError):
            IsoSpec()

    def test_bad_url_scheme_rejected(self):
        with pytest.raises(ValueError):
            IsoSpec(url="ftp://example.com/os.iso")

    def test_http_url_accepted(self):
        s = IsoSpec.from_url("http://example.com/os.iso")
        assert s.url.startswith("http://")


# ======================================================================
# prepare() — local path
# ======================================================================

class TestIsoManagerLocal:
    def test_valid_local_iso(self, tmp_path):
        iso = tmp_path / "test.iso"
        iso.write_bytes(b"\x00" * (2 * 1024 * 1024))  # 2 MB fake ISO
        result = prepare(IsoSpec.from_path(str(iso)))
        assert result == str(iso)

    def test_missing_file_raises(self):
        with pytest.raises(IsoError) as exc:
            prepare(IsoSpec.from_path("/nonexistent/path/test.iso"))
        assert exc.value.code == "ISO_NOT_FOUND"

    def test_too_small_raises(self, tmp_path):
        iso = tmp_path / "tiny.iso"
        iso.write_bytes(b"\x00" * 100)  # < 1 MB
        with pytest.raises(IsoError) as exc:
            prepare(IsoSpec.from_path(str(iso)))
        assert exc.value.code == "ISO_TOO_SMALL"

    def test_sha256_verification_pass(self, tmp_path):
        data = b"\x5a" * (2 * 1024 * 1024)
        iso  = tmp_path / "ok.iso"
        iso.write_bytes(data)
        sha  = hashlib.sha256(data).hexdigest()
        result = prepare(IsoSpec.from_path(str(iso), sha256=sha))
        assert result == str(iso)

    def test_sha256_verification_fail(self, tmp_path):
        iso = tmp_path / "bad.iso"
        iso.write_bytes(b"\xff" * (2 * 1024 * 1024))
        with pytest.raises(IsoError) as exc:
            prepare(IsoSpec.from_path(str(iso), sha256="a" * 64))
        assert exc.value.code == "SHA256_MISMATCH"
        assert "a" * 64 in str(exc.value)      # expected hash shown
        assert "\xff" not in str(exc.value)    # raw bytes not leaked


# ======================================================================
# Virtual Disk
# ======================================================================

class TestDisk:
    def test_disk_spec_requires_positive_size(self):
        with pytest.raises(ValueError):
            DiskSpec(path="/tmp/x.qcow2", size_gb=0)

    def test_disk_spec_requires_path(self):
        with pytest.raises(ValueError):
            DiskSpec(path="", size_gb=1)

    @pytest.mark.skipif(
        not __import__("shutil").which("qemu-img"),
        reason="qemu-img not installed"
    )
    def test_create_and_validate(self, tmp_path):
        spec = DiskSpec(path=str(tmp_path / "test.qcow2"), size_gb=1)
        path = create_disk(spec)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000
        info = validate(path)
        assert info["ok"] is True
        assert info["format"] in ("qcow2", "?")

    @pytest.mark.skipif(
        not __import__("shutil").which("qemu-img"),
        reason="qemu-img not installed"
    )
    def test_create_idempotent(self, tmp_path):
        spec = DiskSpec(path=str(tmp_path / "idem.qcow2"), size_gb=1)
        p1 = create_disk(spec)
        p2 = create_disk(spec)   # should reuse
        assert p1 == p2

    def test_validate_missing_raises(self):
        with pytest.raises(DiskError) as exc:
            validate("/nonexistent/disk.qcow2")
        assert exc.value.code == "DISK_NOT_FOUND"


# ======================================================================
# GuestConfig — generic, no os_type presets
# ======================================================================

class TestGuestConfig:
    def test_from_url(self):
        from tek_runtime.guest_config import GuestConfig
        g = GuestConfig.from_url("https://x.com/os.iso", name="TestOS")
        assert g.display_name == "TestOS"
        assert g.iso.url == "https://x.com/os.iso"

    def test_from_local(self, tmp_path):
        from tek_runtime.guest_config import GuestConfig
        iso = tmp_path / "os.iso"
        iso.write_bytes(b"\x00")
        g = GuestConfig.from_local(str(iso), name="TestOS")
        assert g.iso.path == str(iso)

    def test_for_alpine(self):
        from tek_runtime.guest_config import GuestConfig
        g = GuestConfig.for_alpine()
        assert g.iso.url == "alpine"

    def test_firmware_validates(self):
        from tek_runtime.guest_config import GuestConfig
        with pytest.raises(ValueError, match="firmware"):
            GuestConfig(iso=IsoSpec.alpine(), firmware="dos")

    def test_machine_validates(self):
        from tek_runtime.guest_config import GuestConfig
        with pytest.raises(ValueError, match="machine"):
            GuestConfig(iso=IsoSpec.alpine(), machine="vbox")

    def test_needs_disk_true(self):
        from tek_runtime.guest_config import GuestConfig
        g = GuestConfig(iso=IsoSpec.alpine(), disk_size_gb=10)
        assert g.needs_disk is True

    def test_needs_disk_false(self):
        from tek_runtime.guest_config import GuestConfig
        g = GuestConfig(iso=IsoSpec.alpine(), disk_size_gb=0)
        assert g.needs_disk is False

    def test_windows_warns(self, tmp_path):
        import warnings
        from tek_runtime.guest_config import GuestConfig
        iso = tmp_path / "win.iso"
        iso.write_bytes(b"\x00")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            g = GuestConfig.for_windows(str(iso))
        assert any("NOT TESTED" in str(x.message) for x in w)
        assert g.machine == "q35"
        assert g.firmware == "uefi"

    def test_no_alpine_lock_in(self):
        """UNIT: GuestConfig works with any ISO, not just Alpine."""
        from tek_runtime.guest_config import GuestConfig
        g = GuestConfig.from_url("https://example.com/debian.iso", name="Debian 12")
        assert "Alpine" not in g.display_name
        assert g.iso.url != "alpine"


# ======================================================================
# QEMU argument generation (unit — no real QEMU)
# ======================================================================

class TestQemuArgs:
    """Verify the QEMU command includes the right flags for each config."""

    def _capture_qemu_cmd(self, monkeypatch, **kwargs):
        """Run qemu.start() with mocked Popen and return the args list."""
        import tek_runtime.qemu as q
        import os, subprocess
        captured = []

        class FakeProc:
            pid = 99999
            def poll(self): return None
            def wait(self, timeout=None): return 0

        def fake_popen(cmd, **kw):
            captured.extend(cmd)
            return FakeProc()

        def fake_exists(p):
            # Monitor socket "exists" so startup proceeds
            if p == q._MON_SOCK: return True
            return False

        monkeypatch.setattr(q, "_proc", None)
        monkeypatch.setattr(q, "_log_fd", None)
        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        monkeypatch.setattr(q, "_set_vnc_password", lambda pw: None)
        monkeypatch.setattr(os.path, "exists", fake_exists)
        monkeypatch.setattr(os, "remove", lambda p: None)

        defaults = dict(iso_path="/fake.iso", vcpu=1, ram_mb=512, vnc_password="pw")
        defaults.update(kwargs)
        q.start(**defaults)
        monkeypatch.setattr(q, "_proc", None)
        monkeypatch.setattr(q, "_log_fd", None)
        return captured

    def test_bios_has_no_pflash(self, monkeypatch):
        args = self._capture_qemu_cmd(monkeypatch, firmware="bios")
        assert "pflash" not in " ".join(args)

    def test_q35_machine_in_args(self, monkeypatch):
        args = self._capture_qemu_cmd(monkeypatch, machine="q35", firmware="bios")
        assert "q35" in args

    def test_pc_machine_in_args(self, monkeypatch):
        args = self._capture_qemu_cmd(monkeypatch, machine="pc", firmware="bios")
        assert "pc" in args

    def test_uses_qmp_not_hmp(self, monkeypatch):
        args = self._capture_qemu_cmd(monkeypatch, firmware="bios")
        assert "-qmp" in args and "-monitor" not in args

    def test_cdrom_in_args(self, monkeypatch):
        args = self._capture_qemu_cmd(monkeypatch, iso_path="/test.iso", firmware="bios")
        assert "/test.iso" in args

    def test_disk_in_args(self, monkeypatch):
        args = self._capture_qemu_cmd(
            monkeypatch, firmware="bios", disk_path="/tmp/disk.qcow2"
        )
        assert any("disk.qcow2" in a for a in args)

    def test_extra_args_appended(self, monkeypatch):
        args = self._capture_qemu_cmd(
            monkeypatch, firmware="bios",
            extra_args=["-device", "usb-tablet"]
        )
        assert "usb-tablet" in args

    @pytest.mark.skip(reason="NOT_RUN: requires real QEMU on Kaggle")
    def test_qemu_starts_on_kaggle():
        pass
