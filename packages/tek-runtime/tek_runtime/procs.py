"""Find processes by program name via /proc.

`pgrep -x NAME` compares against the kernel `comm`, which Linux truncates to 15
characters, so `pgrep -x qemu-system-x86_64` can NEVER match. We read argv instead.
"""
from __future__ import annotations

import os

_INTERPRETERS = ("python", "sh", "bash")


def pids_by_name(name: str) -> list[int]:
    """PIDs whose program (argv[0], or the script after an interpreter) is `name`."""
    found: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue                      # process exited while scanning
        if not argv:
            continue                      # kernel thread / zombie
        names = [os.path.basename(argv[0])]
        if len(argv) > 1 and names[0].startswith(_INTERPRETERS):
            names.append(os.path.basename(argv[1]))
        if name in names:
            found.append(int(entry))
    return found
