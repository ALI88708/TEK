"""frp-based relay client (frpc) for the Kaggle runtime.

The User-Owned Relay allows the user's own Windows/Linux machine to act as
a public relay server instead of depending on Cloudflare Quick Tunnel.

Architecture:
  User's machine (frps) ←── outbound TCP ──── Kaggle (frpc)
                              port 7000
  Controller connects to localhost:16080 (relayed to Kaggle's authproxy:6080)

Requirements on user's machine:
  - Public IP address (or port-forwarding to their machine)
  - Port 7000 open for inbound frpc connections
  - frps running (managed by RelayManager in tek-controller)

Requirements on Kaggle:
  - frpc binary (downloaded here)
  - TEK_RELAY_HOST set to the user's public IP/hostname
  - TEK_RELAY_PORT set to the frps bind port (default 7000)
  - TEK_RELAY_TOKEN set to the session-derived relay token

NOT REQUIRED: Cloudflare account, external VPS, or any paid service.
LIMITATION: If the user's machine is behind CGNAT or a firewall that blocks
  inbound connections, the relay cannot work. See RelayManager for the
  NAT check that runs on the controller side.
"""
from __future__ import annotations

import os
import platform
import stat
import subprocess
import tempfile
import time
import urllib.request

_FRP_VERSION = "0.60.0"   # pin to a known-good release
_PROC: subprocess.Popen | None = None
_CONFIG_FILE: str | None = None

# Map (system, machine) → frp archive name
_FRP_PLATFORMS = {
    ("Linux",  "x86_64"):  f"frp_{_FRP_VERSION}_linux_amd64",
    ("Linux",  "aarch64"): f"frp_{_FRP_VERSION}_linux_arm64",
}

_FRP_BASE_URL = (
    f"https://github.com/fatedier/frp/releases/download/"
    f"v{_FRP_VERSION}/"
)


def _frpc_path() -> str:
    return f"/tmp/tek-frpc-{_FRP_VERSION}"


def ensure_frpc() -> str:
    """Download frpc if not already present. Returns the binary path."""
    dest = _frpc_path()
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        return dest

    system  = platform.system()
    machine = platform.machine()
    key     = (system, machine)
    if key not in _FRP_PLATFORMS:
        raise RuntimeError(
            f"No frpc binary for {system}/{machine}. "
            "Supported: Linux x86_64, Linux aarch64."
        )

    archive_name = _FRP_PLATFORMS[key]
    url          = _FRP_BASE_URL + archive_name + ".tar.gz"
    archive      = f"/tmp/{archive_name}.tar.gz"

    print(f"  Downloading frpc ({_FRP_VERSION}) …")
    r = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", archive, url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"frpc download failed: {r.stderr[:500]}")

    # Extract just the frpc binary
    subprocess.run(
        ["tar", "-xzf", archive, "-C", "/tmp/",
         f"{archive_name}/frpc", "--strip-components=1"],
        check=True, capture_output=True,
    )
    extracted = f"/tmp/frpc"
    if os.path.exists(extracted):
        os.rename(extracted, dest)
    else:
        raise RuntimeError("frpc binary not found after extraction.")

    os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
             stat.S_IROTH | stat.S_IXOTH)
    os.remove(archive)
    return dest


def _write_config(
    server_addr: str,
    server_port: int,
    relay_token: str,
    authproxy_port: int = 6080,
    relay_authproxy_port: int = 16080,
) -> str:
    """Write frpc TOML config and return path."""
    config = f"""
serverAddr = "{server_addr}"
serverPort = {server_port}

[auth]
method = "token"
token = "{relay_token}"

[[proxies]]
name = "tek-authproxy"
type = "tcp"
localIP = "127.0.0.1"
localPort = {authproxy_port}
remotePort = {relay_authproxy_port}
"""
    fd, path = tempfile.mkstemp(suffix=".toml", prefix="tek-frpc-")
    with os.fdopen(fd, "w") as f:
        f.write(config.strip())
    return path


def start(
    server_addr: str,
    server_port: int,
    relay_token: str,
    authproxy_port: int = 6080,
    relay_authproxy_port: int = 16080,
) -> None:
    """Start the frpc relay client. Idempotent."""
    global _PROC, _CONFIG_FILE

    if _PROC is not None and _PROC.poll() is None:
        print("  frpc already running — reusing.")
        return

    frpc   = ensure_frpc()
    config = _write_config(
        server_addr, server_port, relay_token,
        authproxy_port, relay_authproxy_port,
    )
    _CONFIG_FILE = config

    _PROC = subprocess.Popen(
        [frpc, "-c", config],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Give frpc time to connect
    for _ in range(20):
        time.sleep(0.5)
        if _PROC.poll() is not None:
            raise RuntimeError(
                f"frpc exited immediately (code {_PROC.returncode}). "
                "Check server_addr, server_port, and relay_token."
            )
        # frpc doesn't expose a local port we can probe, so just wait for startup
    print(f"  frpc connected to {server_addr}:{server_port}")


def is_alive() -> bool:
    return _PROC is not None and _PROC.poll() is None


def stop() -> None:
    global _PROC, _CONFIG_FILE
    if _PROC and _PROC.poll() is None:
        _PROC.terminate()
        try:
            _PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _PROC.kill()
    _PROC = None
    if _CONFIG_FILE and os.path.exists(_CONFIG_FILE):
        try:
            os.remove(_CONFIG_FILE)
        except OSError:
            pass
    _CONFIG_FILE = None
