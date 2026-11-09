"""Idempotent dependency installation. Raises RuntimeError on failure."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess


def _apt(*packages: str) -> None:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    subprocess.run(
        ["apt-get", "-qq", "install", "-y", *packages],
        check=True, env=env, capture_output=True,
    )


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n{r.stderr.decode()[-1000:]}"
        )


def ensure_qemu() -> None:
    if shutil.which("qemu-system-x86_64"):
        return
    subprocess.run(["apt-get", "-qq", "update"], capture_output=True)
    _apt("qemu-system-x86", "qemu-utils")


def ensure_novnc() -> None:
    if shutil.which("websockify") and os.path.isdir("/usr/share/novnc"):
        return
    _apt("novnc", "websockify")


def ensure_cloudflared() -> None:
    if shutil.which("cloudflared"):
        return
    dest = "/usr/local/bin/cloudflared"
    _run([
        "curl", "-fsSL", "-o", dest,
        "https://github.com/cloudflare/cloudflared/releases/latest/download/"
        "cloudflared-linux-amd64",
    ])
    os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
             stat.S_IROTH | stat.S_IXOTH)


def install_all() -> None:
    ensure_qemu()
    ensure_novnc()
    ensure_cloudflared()
