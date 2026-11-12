"""Unit tests for GuestConfig — multi-OS guest settings."""
from __future__ import annotations

import sys
import warnings

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
from tek_runtime.guest_config import GuestConfig


class TestGuestConfig:
    def test_linux_preset_is_tested(self):
        """Alpine / generic Linux preset must be marked tested."""
        g = GuestConfig(iso_path="/tmp/alpine.iso", os_type="linux")
        assert g.boot_order == "d"
        assert g.machine == "pc"
        assert g.extra_qemu_args == []

    def test_windows_preset_issues_warning(self):
        """Windows OS type must warn it is untested."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            g = GuestConfig(iso_path="/tmp/win.iso", os_type="windows")
        assert any("NOT TESTED" in str(warning.message) for warning in w), \
            "Expected an 'NOT TESTED' warning for windows os_type"
        assert g.machine == "q35"
        assert any("usb-tablet" in arg for arg in g.extra_qemu_args)

    def test_unknown_os_type_raises(self):
        with pytest.raises(ValueError, match="Unknown os_type"):
            GuestConfig(iso_path="/tmp/x.iso", os_type="dos")

    def test_display_name_defaults_to_filename(self):
        g = GuestConfig(iso_path="/path/to/my-linux.iso")
        assert g.display_name == "my-linux.iso"

    def test_display_name_explicit(self):
        g = GuestConfig(iso_path="/tmp/x.iso", display_name="Custom OS")
        assert g.display_name == "Custom OS"

    def test_for_alpine_factory(self):
        g = GuestConfig.for_alpine("/tmp/alpine-virt.iso")
        assert g.os_type == "linux"
        assert g.display_name == "Alpine Linux"
        assert g.boot_order == "d"

    def test_for_custom_linux_factory(self):
        g = GuestConfig.for_custom_linux("/tmp/debian.iso", "Debian 12")
        assert g.os_type == "linux"
        assert g.display_name == "Debian 12"

    def test_for_windows_factory_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            g = GuestConfig.for_windows("/tmp/win11.iso")
        assert any("NOT TESTED" in str(warning.message) for warning in w)
        assert g.os_type == "windows"
        assert g.display_name == "Windows"

    def test_disk_path_defaults_none(self):
        g = GuestConfig(iso_path="/tmp/x.iso")
        assert g.disk_path is None

    def test_custom_extra_args_override_preset(self):
        """Explicitly provided extra_args should NOT be overridden by preset."""
        g = GuestConfig(
            iso_path="/tmp/win.iso",
            os_type="windows",
            extra_qemu_args=["-device", "my-custom-device"],
        )
        # The custom args should be kept as-is
        assert "-device" in g.extra_qemu_args
        assert "my-custom-device" in g.extra_qemu_args

    def test_preset_notes_returns_string(self):
        g = GuestConfig(iso_path="/tmp/alpine.iso")
        notes = g.preset_notes()
        assert isinstance(notes, str) and len(notes) > 0
