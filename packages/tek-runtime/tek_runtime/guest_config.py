"""Guest OS configuration — generic, OS-agnostic.

GuestConfig holds everything that depends on the guest's setup:
  - ISO source (local path, URL, or the Alpine shorthand for testing)
  - Hardware: CPU cores, RAM, disk size
  - Firmware: BIOS or UEFI
  - QEMU machine type
  - Display and boot options

Design rule: GuestConfig has NO built-in OS presets.
  There are factory helpers for common setups, but they carry no special
  QEMU magic — they are convenience wrappers around the same fields.
  The old os_type="windows"/"bsd" preset system is removed; callers
  set machine/boot_order/extra_qemu_args directly.

Alpine is kept only as a named factory (`for_alpine`) and as the default
when no ISO is specified — it is NOT a required dependency of TEK.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .iso_manager import IsoSpec


@dataclass
class GuestConfig:
    """Full configuration for a guest VM session.

    Parameters
    ----------
    iso
        IsoSpec describing the boot ISO.  Use IsoSpec.alpine() for the
        default Alpine test image, or IsoSpec.from_url(...) / .from_path(...).
    display_name
        Human label shown in Controller and logs.
    vcpu
        Virtual CPU count.  None = auto-assign from ResourcePlan.
    ram_mb
        Guest RAM in MB.  None = auto-assign from ResourcePlan.
    disk_size_gb
        Size of QCOW2 virtual disk to create.  0 = no persistent disk
        (live ISO only).  Kaggle sessions are temporary — disk is lost
        when the session ends unless explicitly exported.
    firmware
        "bios" (default, most compatible) or "uefi" (requires OVMF).
    machine
        QEMU -machine argument.  "pc" (i440FX) or "q35" (ICH9).
    boot_order
        QEMU boot order string.  "d" = CD-ROM first, "c" = HDD first,
        "dc" = CD-ROM then HDD.
    extra_qemu_args
        Raw QEMU arguments appended after all auto-generated ones.
    disk_path
        Pre-existing QCOW2 path.  If set, disk_size_gb is ignored and
        this disk is attached as-is.
    """
    iso:            IsoSpec
    display_name:   str              = ""
    vcpu:           int | None       = None   # None = ResourcePlan decides
    ram_mb:         int | None       = None   # None = ResourcePlan decides
    disk_size_gb:   float            = 0.0    # 0 = no disk, > 0 = create
    firmware:       str              = "bios" # "bios" | "uefi"
    machine:        str              = "pc"   # "pc" | "q35"
    boot_order:     str              = "d"    # QEMU boot order
    extra_qemu_args: list[str]       = field(default_factory=list)
    disk_path:      str | None       = None   # pre-existing disk path

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.iso.display_name
        if self.firmware not in ("bios", "uefi"):
            raise ValueError(
                f"firmware must be 'bios' or 'uefi'; got {self.firmware!r}"
            )
        if self.machine not in ("pc", "q35"):
            raise ValueError(
                f"machine must be 'pc' or 'q35'; got {self.machine!r}"
            )
        if self.vcpu is not None and self.vcpu < 1:
            raise ValueError(f"vcpu must be >= 1; got {self.vcpu}")
        if self.ram_mb is not None and self.ram_mb < 256:
            raise ValueError(f"ram_mb must be >= 256; got {self.ram_mb}")

    # -- factories --------------------------------------------------------

    @classmethod
    def for_alpine(cls, iso_path: str | None = None) -> "GuestConfig":
        """Alpine Linux test image — downloads automatically if iso_path is None."""
        iso = IsoSpec.from_path(iso_path) if iso_path else IsoSpec.alpine()
        return cls(iso=iso, display_name="Alpine Linux", boot_order="d")

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        sha256: str = "",
        name: str = "",
        disk_size_gb: float = 0.0,
        firmware: str = "bios",
        machine: str = "pc",
        vcpu: int | None = None,
        ram_mb: int | None = None,
        boot_order: str = "d",
        extra_qemu_args: list[str] | None = None,
    ) -> "GuestConfig":
        """Create from a direct ISO download URL."""
        iso = IsoSpec.from_url(url, sha256=sha256, name=name)
        return cls(
            iso=iso,
            display_name=name or iso.display_name,
            disk_size_gb=disk_size_gb,
            firmware=firmware,
            machine=machine,
            vcpu=vcpu,
            ram_mb=ram_mb,
            boot_order=boot_order,
            extra_qemu_args=list(extra_qemu_args or []),
        )

    @classmethod
    def from_local(
        cls,
        path: str,
        *,
        sha256: str = "",
        name: str = "",
        disk_size_gb: float = 0.0,
        firmware: str = "bios",
        machine: str = "pc",
        vcpu: int | None = None,
        ram_mb: int | None = None,
        boot_order: str = "d",
        extra_qemu_args: list[str] | None = None,
    ) -> "GuestConfig":
        """Create from a local ISO file path."""
        iso = IsoSpec.from_path(path, sha256=sha256, name=name)
        return cls(
            iso=iso,
            display_name=name or iso.display_name,
            disk_size_gb=disk_size_gb,
            firmware=firmware,
            machine=machine,
            vcpu=vcpu,
            ram_mb=ram_mb,
            boot_order=boot_order,
            extra_qemu_args=list(extra_qemu_args or []),
        )

    @classmethod
    def for_windows(cls, iso_path: str, *, disk_size_gb: float = 40.0) -> "GuestConfig":
        """Windows ISO — q35 machine, UEFI recommended, USB tablet for mouse.

        NOT TESTED on Kaggle TCG. UEFI requires OVMF to be installed.
        """
        import warnings
        warnings.warn(
            "GuestConfig.for_windows: Windows on Kaggle TCG is NOT TESTED. "
            "UEFI requires OVMF. Mouse requires usb-tablet device.",
            stacklevel=2,
        )
        return cls(
            iso=IsoSpec.from_path(iso_path, name="Windows"),
            display_name="Windows",
            machine="q35",
            firmware="uefi",
            disk_size_gb=disk_size_gb,
            extra_qemu_args=["-device", "usb-tablet"],
        )

    # -- helpers ----------------------------------------------------------

    @property
    def needs_disk(self) -> bool:
        return self.disk_size_gb > 0 and self.disk_path is None

    @property
    def has_disk(self) -> bool:
        return bool(self.disk_path) or self.disk_size_gb > 0

    def preset_notes(self) -> str:
        """Human-readable notes about this config."""
        notes = [f"ISO: {self.iso.display_name}"]
        if self.firmware == "uefi":
            notes.append("Firmware: UEFI (requires OVMF on host)")
        if self.disk_size_gb > 0:
            notes.append(
                f"Disk: {self.disk_size_gb:.0f} GB QCOW2 "
                "(NOTE: Kaggle sessions are temporary — disk lost on session end)"
            )
        return "  ".join(notes)
