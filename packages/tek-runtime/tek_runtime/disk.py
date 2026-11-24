"""Virtual Disk Management — QCOW2 lifecycle.

Creates and manages QCOW2 virtual disk images for guest VMs.

Persistence note:
  Kaggle sessions are TEMPORARY. A disk created here exists only as long as
  the Kaggle kernel is running. When the session ends, the disk is lost unless
  the user has exported it to a persistent location (Kaggle dataset, Google
  Drive, etc.). TEK does not currently implement automatic disk persistence.
  This is documented here and in the UI — never claimed as a solved problem.

Usage:
    spec = DiskSpec(path="/kaggle/temp/my-vm.qcow2", size_gb=10)
    path = create(spec)   # → "/kaggle/temp/my-vm.qcow2"
    # pass path to QEMU via -drive
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


class DiskError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message


@dataclass
class DiskSpec:
    """Specification for a virtual disk image."""
    path:      str           # absolute path for the disk file
    size_gb:   float         # disk size in GB
    fmt:       str   = "qcow2"   # always qcow2 for now

    def __post_init__(self) -> None:
        if self.size_gb <= 0:
            raise ValueError(f"DiskSpec.size_gb must be > 0; got {self.size_gb}")
        if not self.path:
            raise ValueError("DiskSpec.path must not be empty.")


def create(spec: DiskSpec, *, overwrite: bool = False) -> str:
    """Create a new QCOW2 disk image.

    Returns the path to the created disk.
    Raises DiskError if creation fails.

    If the file already exists and `overwrite=False`, the existing file is
    reused (idempotent for notebook cell re-runs).
    """
    if os.path.exists(spec.path):
        if not overwrite:
            size_mb = os.path.getsize(spec.path) // (1024 * 1024)
            print(f"  Disk exists ({size_mb} MB), reusing: {spec.path}")
            return spec.path
        os.remove(spec.path)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(spec.path) or ".", exist_ok=True)

    r = subprocess.run(
        [
            "qemu-img", "create",
            "-f", spec.fmt,
            spec.path,
            f"{spec.size_gb:.0f}G",
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise DiskError(
            "DISK_CREATE_FAILED",
            f"qemu-img create failed:\n{r.stderr[:500]}",
        )
    print(f"  Disk created: {spec.path}  ({spec.size_gb:.0f} GB QCOW2)")
    return spec.path


def validate(path: str) -> dict:
    """Run qemu-img check on a disk and return info dict.

    Returns {"ok": True, "format": ..., "virtual_size": ...} on success.
    Raises DiskError if the disk is corrupt.
    """
    if not os.path.exists(path):
        raise DiskError("DISK_NOT_FOUND", f"Disk file not found: {path}")

    r = subprocess.run(
        ["qemu-img", "check", "-q", path],
        capture_output=True, text=True,
    )
    # qemu-img check returns 0 for clean, non-zero for errors
    if r.returncode not in (0, 1):   # 1 = leaks only (non-critical)
        raise DiskError(
            "DISK_CORRUPT",
            f"qemu-img check found errors in {path}:\n{r.stderr[:300]}",
        )

    info_r = subprocess.run(
        ["qemu-img", "info", "--output=json", path],
        capture_output=True, text=True,
    )
    if info_r.returncode == 0:
        import json
        try:
            data = json.loads(info_r.stdout)
            return {
                "ok":          True,
                "format":      data.get("format", "?"),
                "virtual_size": data.get("virtual-size", 0),
                "actual_size":  data.get("actual-size", 0),
                "path":        path,
            }
        except (json.JSONDecodeError, KeyError):
            pass
    return {"ok": True, "path": path}


def default_path(session_id: str, cache_dir: str | None = None) -> str:
    """Generate a default disk path for a session."""
    base = cache_dir or ("/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp")
    return os.path.join(base, f"tek-disk-{session_id}.qcow2")
