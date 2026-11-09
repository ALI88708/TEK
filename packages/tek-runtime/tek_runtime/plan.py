"""Turn raw resource facts into a ResourcePlan with headroom."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

_GiB = 1024 ** 3
_MiB = 1024 ** 2

_MIN_GUEST_RAM_MB = 512
_MIN_GUEST_DISK_GB = 2.0


class PlanError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ResourcePlan:
    vcpu: int
    ram_mb: int
    disk_gb: float
    host_reserve_vcpu: int
    host_reserve_mb: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"vcpu": self.vcpu, "ram_mb": self.ram_mb, "disk_gb": self.disk_gb}


def make_plan(cpu_count: int, ram_bytes: int, disk_free_bytes: int) -> ResourcePlan:
    warnings: list[str] = []

    # --- CPU ---
    reserve_vcpu = max(1, math.ceil(cpu_count * 0.25))
    guest_vcpu = max(1, cpu_count - reserve_vcpu)
    if guest_vcpu >= cpu_count:
        warnings.append("Guest receives 100 % of vCPUs; host may starve.")

    # --- RAM ---
    reserve_bytes = max(2 * _GiB, int(ram_bytes * 0.10))
    guest_ram_bytes = max(0, ram_bytes - reserve_bytes)
    guest_ram_mb = guest_ram_bytes // _MiB
    if guest_ram_mb < _MIN_GUEST_RAM_MB:
        raise PlanError(
            "RESOURCE_PLAN_UNSATISFIABLE",
            f"Only {guest_ram_mb} MB available for guest after host reserve; "
            f"minimum is {_MIN_GUEST_RAM_MB} MB.",
        )

    # --- Disk ---
    # Keep 20 % headroom for the OS overlay and export workspace.
    guest_disk_gb = round(disk_free_bytes / _GiB * 0.80, 1)
    if guest_disk_gb < _MIN_GUEST_DISK_GB:
        raise PlanError(
            "DISK_FULL",
            f"Only {guest_disk_gb:.1f} GB free after headroom; "
            f"minimum is {_MIN_GUEST_DISK_GB} GB.",
        )

    return ResourcePlan(
        vcpu=guest_vcpu,
        ram_mb=int(guest_ram_mb),
        disk_gb=guest_disk_gb,
        host_reserve_vcpu=reserve_vcpu,
        host_reserve_mb=int(reserve_bytes // _MiB),
        warnings=warnings,
    )
