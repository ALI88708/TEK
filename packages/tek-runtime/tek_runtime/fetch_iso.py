"""Download and cache a minimal Alpine Linux ISO (Invariant I3 — no binaries in repo)."""
from __future__ import annotations

import os
import re
import subprocess
import urllib.request

_ALPINE_BASE = "https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/"
_CACHE_DIR = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp"


def get_alpine(cache_dir: str | None = None) -> str:
    dest_dir = cache_dir or _CACHE_DIR
    dest = os.path.join(dest_dir, "alpine-virt.iso")

    if os.path.exists(dest) and os.path.getsize(dest) > 10 * 1024 * 1024:
        print(f"  ISO cached: {dest}  ({os.path.getsize(dest) // (1024**2)} MB)")
        return dest

    html = urllib.request.urlopen(_ALPINE_BASE, timeout=60).read().decode()
    names = re.findall(r'href="(alpine-virt-[\d.]+-x86_64\.iso)"', html)
    if not names:
        raise RuntimeError("No Alpine virt ISO found in the mirror listing.")
    name = max(names, key=lambda n: tuple(int(x) for x in re.findall(r"\d+", n)[:3]))
    print(f"  Downloading: {name}")

    r = subprocess.run(
        ["curl", "-fL", "--retry", "3", "-#", "-o", dest, _ALPINE_BASE + name],
        check=False,
    )
    if r.returncode != 0 or not os.path.exists(dest):
        raise RuntimeError(f"ISO download failed for {name}")

    print(f"  ISO ready: {dest}  ({os.path.getsize(dest) // (1024**2)} MB)")
    return dest
