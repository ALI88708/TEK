"""Read actual cgroup/kernel limits. No hardcoded constants (Invariant I2)."""
from __future__ import annotations

import math
import os
import shutil


def _read(path: str, default: str | None = None) -> str | None:
    try:
        return open(path).read().strip()
    except OSError:
        return default


def cpu_count() -> int:
    """Effective vCPU count from affinity + cgroup quota."""
    try:
        affinity = len(os.sched_getaffinity(0))
    except AttributeError:
        affinity = os.cpu_count() or 1

    # cgroup v2
    v2 = _read("/sys/fs/cgroup/cpu.max")
    if v2 and not v2.startswith("max"):
        try:
            quota_s, period_s = v2.split()
            cgroup = math.ceil(int(quota_s) / int(period_s))
            return min(affinity, cgroup)
        except (ValueError, ZeroDivisionError):
            pass

    # cgroup v1
    quota = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period = _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota and period and quota != "-1":
        try:
            cgroup = math.ceil(int(quota) / int(period))
            return min(affinity, cgroup)
        except (ValueError, ZeroDivisionError):
            pass

    return affinity


def ram_bytes() -> int:
    """Available RAM in bytes from cgroup + /proc/meminfo."""
    cgroup_limit = 2**62  # effectively unlimited

    v2 = _read("/sys/fs/cgroup/memory.max")
    if v2 and v2 != "max":
        try:
            cgroup_limit = int(v2)
        except ValueError:
            pass
    else:
        v1 = _read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        if v1:
            try:
                cgroup_limit = int(v1)
            except ValueError:
                pass

    available = 0
    for line in (_read("/proc/meminfo") or "").splitlines():
        if line.startswith("MemAvailable:"):
            available = int(line.split()[1]) * 1024
            break

    return min(cgroup_limit, available) if available else cgroup_limit


def disk_free_bytes(path: str | None = None) -> int:
    """Free bytes on the writable scratch partition."""
    candidates = [path, "/kaggle/temp", "/kaggle/working", "/tmp"]
    for p in candidates:
        if p and os.path.isdir(p):
            try:
                return shutil.disk_usage(p).free
            except OSError:
                continue
    return 0


def has_kvm() -> bool:
    return os.path.exists("/dev/kvm")


def summary() -> dict:
    cpu = cpu_count()
    ram = ram_bytes()
    disk = disk_free_bytes()
    kvm = has_kvm()
    return {
        "cpu": cpu,
        "ram_bytes": ram,
        "disk_free_bytes": disk,
        "has_kvm": kvm,
    }
