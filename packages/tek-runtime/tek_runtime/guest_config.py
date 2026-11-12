"""Guest OS configuration — separates VM settings from Runtime lifecycle.

Design:
  GuestConfig holds everything that depends on the guest OS choice.
  The runtime session uses it to configure QEMU without hard-coding Alpine.

Supported OS types (tested status):
  "linux"   — Any Linux LiveCD ISO. Alpine tested on Kaggle TCG.
  "windows" — Windows ISO. NOT YET TESTED. Requires UEFI or BIOS.
  "bsd"     — FreeBSD etc. NOT YET TESTED.

Do NOT claim an OS type works until it has been tested on Kaggle.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# ── OS presets ──────────────────────────────────────────────────────────────
# These define QEMU-level settings per OS family.
# A preset is a STARTING POINT; the caller can override any field.
# "tested" = True means this has been verified to run on Kaggle TCG.

_PRESETS: dict[str, dict] = {
    "linux": {
        "boot_order":    "d",           # CD-ROM first
        "machine":       "pc",          # i440FX (most compatible)
        "extra_args":    [],
        "tested":        True,
        "notes":         "Any Linux LiveCD. Alpine Linux verified on Kaggle TCG.",
    },
    "windows": {
        "boot_order":    "d",
        "machine":       "q35",         # Windows prefers Q35 chipset
        "extra_args":    [
            "-device", "usb-tablet",   # Windows needs absolute mouse input
        ],
        "tested":        False,
        "notes":         "NOT TESTED on Kaggle. May need UEFI (OVMF). "
                         "Windows 10/11 requires USB tablet for correct mouse.",
    },
    "bsd": {
        "boot_order":    "d",
        "machine":       "pc",
        "extra_args":    [],
        "tested":        False,
        "notes":         "NOT TESTED on Kaggle.",
    },
}


@dataclass
class GuestConfig:
    """Configuration for a guest OS session.

    Parameters
    ----------
    iso_path
        Path to the ISO file on the Kaggle host.
        For Alpine: auto-downloaded by fetch_iso.get_alpine().
        For custom: provide a full path; validation is the caller's responsibility.
    os_type
        "linux" (default), "windows", or "bsd".
        Only "linux" is tested; others are provided as a starting point.
    display_name
        Human-readable name shown in logs and the descriptor.
        Defaults to the ISO filename.
    boot_order
        QEMU boot order string. "d" = CD-ROM first (default).
    machine
        QEMU -machine argument. "pc" or "q35".
        Windows needs "q35".
    disk_path
        Optional path to a QCOW2 persistent disk image.
        None = no persistent disk (pure LiveCD / stateless session).
    extra_qemu_args
        Additional raw QEMU arguments appended after all others.
        Use for OS-specific tweaks not covered by the preset.
    """
    iso_path:        str
    os_type:         str              = "linux"
    display_name:    str              = ""
    boot_order:      str              = "d"
    machine:         str              = "pc"
    disk_path:       str | None       = None
    extra_qemu_args: list[str]        = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = os.path.basename(self.iso_path)
        if self.os_type not in _PRESETS:
            raise ValueError(
                f"Unknown os_type {self.os_type!r}. "
                f"Valid: {list(_PRESETS)}"
            )
        preset = _PRESETS[self.os_type]
        if not preset["tested"]:
            import warnings
            warnings.warn(
                f"GuestConfig os_type={self.os_type!r} has NOT been tested on Kaggle. "
                f"Notes: {preset['notes']}",
                stacklevel=2,
            )
        # Apply preset defaults only if the caller left them at the dataclass default
        if self.boot_order == "d" and preset["boot_order"] != "d":
            self.boot_order = preset["boot_order"]
        if self.machine == "pc" and preset["machine"] != "pc":
            self.machine = preset["machine"]
        if not self.extra_qemu_args and preset["extra_args"]:
            self.extra_qemu_args = list(preset["extra_args"])

    def preset_notes(self) -> str:
        return _PRESETS[self.os_type]["notes"]

    @classmethod
    def for_alpine(cls, iso_path: str) -> "GuestConfig":
        """Pre-configured for Alpine Linux LiveCD (tested)."""
        return cls(
            iso_path=iso_path,
            os_type="linux",
            display_name="Alpine Linux",
        )

    @classmethod
    def for_custom_linux(cls, iso_path: str, display_name: str = "") -> "GuestConfig":
        """Any Linux LiveCD."""
        return cls(
            iso_path=iso_path,
            os_type="linux",
            display_name=display_name or os.path.basename(iso_path),
        )

    @classmethod
    def for_windows(cls, iso_path: str) -> "GuestConfig":
        """Windows ISO — NOT TESTED on Kaggle. Use with caution."""
        return cls(
            iso_path=iso_path,
            os_type="windows",
            display_name="Windows",
        )
