"""RelayManager — frps server for TEK Controller (User-Owned Relay).

The user's machine runs frps. Kaggle runs frpc and connects outbound.
The controller then accesses Kaggle's services via local relay ports.

Port plan (all configurable):
  7000  — frps bind port (frpc connects here from Kaggle)
  7500  — frps dashboard (optional, disabled by default)
  16080 — relay port for Kaggle's authproxy (exposed locally)

Authentication:
  The relay token is derived from the TEK session secret using HKDF,
  so it rotates per session and is never stored separately.

Usage:
    mgr = RelayManager(secret=session_secret)
    mgr.start()           # starts frps
    config = mgr.frpc_env()  # pass to Kaggle as env vars
    # ...
    mgr.stop()
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum, auto

from ..crypto import relay_token as _derive_relay_token


class RelayStatus(Enum):
    STOPPED  = auto()
    STARTING = auto()
    RUNNING  = auto()
    FAILED   = auto()
    NAT_FAIL = auto()   # public access check failed


_FRP_VERSION = "0.60.0"
_FRP_PLATFORMS = {
    ("Windows", "AMD64"):  f"frp_{_FRP_VERSION}_windows_amd64",
    ("Windows", "x86_64"): f"frp_{_FRP_VERSION}_windows_amd64",
    ("Linux",  "x86_64"):  f"frp_{_FRP_VERSION}_linux_amd64",
    ("Darwin", "x86_64"):  f"frp_{_FRP_VERSION}_darwin_amd64",
    ("Darwin", "arm64"):   f"frp_{_FRP_VERSION}_darwin_arm64",
}
_FRP_BASE = (
    f"https://github.com/fatedier/frp/releases/download/"
    f"v{_FRP_VERSION}/"
)


@dataclass
class RelayConfig:
    bind_port:           int   = 7000    # frpc connects here from Kaggle
    relay_authproxy_port: int  = 16080   # local port for Kaggle's authproxy
    enable_dashboard:    bool  = False
    dashboard_port:      int   = 7500


@dataclass
class RelayInfo:
    status:              RelayStatus    = RelayStatus.STOPPED
    public_ip:           str           = ""
    local_ip:            str           = ""
    bind_port:           int           = 7000
    relay_authproxy_port: int          = 16080
    nat_ok:              bool          = False
    error:               str           = ""
    frpc_env:            dict[str, str] = field(default_factory=dict)


class RelayManager:
    """Manages frps on the controller side for the User-Owned Relay."""

    def __init__(
        self,
        secret: bytes,
        config: RelayConfig | None = None,
    ) -> None:
        self.secret  = secret
        self.cfg     = config or RelayConfig()
        self._token  = _derive_relay_token(secret)
        self._proc:  subprocess.Popen | None = None
        self._cfg_f: str | None = None
        self._info   = RelayInfo(bind_port=self.cfg.bind_port,
                                 relay_authproxy_port=self.cfg.relay_authproxy_port)
        self._lock   = threading.Lock()

    # ------------------------------------------------------------------ #

    def start(self, skip_nat_check: bool = False) -> RelayInfo:
        """Start frps and optionally verify public reachability."""
        with self._lock:
            self._info.status = RelayStatus.STARTING
            self._info.error  = ""

        try:
            frps = self._ensure_frps()
        except Exception as exc:
            return self._fail(f"frps download failed: {exc}")

        # Detect local IP
        try:
            self._info.local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            self._info.local_ip = "127.0.0.1"

        # Write config
        cfg_path = self._write_config()
        self._cfg_f = cfg_path

        # Start frps
        try:
            self._proc = subprocess.Popen(
                [frps, "-c", cfg_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            return self._fail(f"Could not start frps: {exc}")

        time.sleep(1.5)
        if self._proc.poll() is not None:
            return self._fail(
                f"frps exited immediately (code {self._proc.returncode}). "
                "Port 7000 may already be in use."
            )

        # Optional NAT check
        if not skip_nat_check:
            from .nat_check import check_public_access, NatType
            result = check_public_access(port=self.cfg.bind_port, probe=True)
            self._info.public_ip = result.public_ip
            self._info.nat_ok    = result.reachable
            if not result.reachable:
                self._info.status = RelayStatus.NAT_FAIL
                self._info.error  = result.friendly()
                # frps is still running; user may still try (e.g. if probe was wrong)
            else:
                self._info.status = RelayStatus.RUNNING
        else:
            self._info.status = RelayStatus.RUNNING

        # Build env vars for Kaggle
        self._info.frpc_env = {
            "TEK_RELAY_HOST":           self._info.public_ip or self._info.local_ip,
            "TEK_RELAY_PORT":           str(self.cfg.bind_port),
            "TEK_RELAY_TOKEN":          self._token,
            "TEK_RELAY_AUTHPROXY_PORT": str(self.cfg.relay_authproxy_port),
        }
        return self._info

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
            if self._cfg_f and os.path.exists(self._cfg_f):
                try:
                    os.remove(self._cfg_f)
                except OSError:
                    pass
            self._cfg_f = None
            self._info.status = RelayStatus.STOPPED

    def status(self) -> RelayInfo:
        with self._lock:
            if (self._info.status == RelayStatus.RUNNING and
                    self._proc and self._proc.poll() is not None):
                self._info.status = RelayStatus.FAILED
                self._info.error  = "frps process exited unexpectedly."
        return self._info

    def connection_url(self) -> str:
        """HTTP URL for the authproxy via relay (for fetch_descriptor)."""
        return f"http://127.0.0.1:{self.cfg.relay_authproxy_port}"

    # ------------------------------------------------------------------ #

    def _write_config(self) -> str:
        dashboard_section = ""
        if self.cfg.enable_dashboard:
            dashboard_section = (
                f"\n[webServer]\n"
                f'addr = "127.0.0.1"\n'
                f"port = {self.cfg.dashboard_port}\n"
            )
        config = (
            f'bindPort = {self.cfg.bind_port}\n'
            f'\n[auth]\nmethod = "token"\ntoken = "{self._token}"\n'
            f'{dashboard_section}'
        )
        fd, path = tempfile.mkstemp(suffix=".toml", prefix="tek-frps-")
        with os.fdopen(fd, "w") as f:
            f.write(config)
        return path

    def _fail(self, msg: str) -> RelayInfo:
        with self._lock:
            self._info.status = RelayStatus.FAILED
            self._info.error  = msg
        return self._info

    def _ensure_frps(self) -> str:
        system  = platform.system()
        machine = platform.machine()
        key     = (system, machine)

        # Check if frps is already on PATH
        if shutil.which("frps"):
            return shutil.which("frps")  # type: ignore

        # Build cache path
        suffix  = ".exe" if system == "Windows" else ""
        dest    = os.path.join(
            tempfile.gettempdir(), f"tek-frps-{_FRP_VERSION}{suffix}"
        )
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            return dest

        archive_name = _FRP_PLATFORMS.get(key)
        if not archive_name:
            raise RuntimeError(
                f"No frps binary for {system}/{machine}. "
                "Download frps manually from https://github.com/fatedier/frp/releases "
                f"(v{_FRP_VERSION}) and add it to PATH."
            )

        ext     = ".zip" if system == "Windows" else ".tar.gz"
        url     = _FRP_BASE + archive_name + ext
        archive = os.path.join(tempfile.gettempdir(), archive_name + ext)

        print(f"  Downloading frps {_FRP_VERSION} …")
        req = urllib.request.Request(url, headers={"User-Agent": "TEK/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            with open(archive, "wb") as f:
                f.write(r.read())

        # Extract
        if system == "Windows":
            import zipfile
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    if name.endswith("frps.exe"):
                        with z.open(name) as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                        break
        else:
            subprocess.run(
                ["tar", "-xzf", archive, "-C", tempfile.gettempdir(),
                 f"{archive_name}/frps", "--strip-components=1"],
                check=True, capture_output=True,
            )
            extracted = os.path.join(tempfile.gettempdir(), "frps")
            if os.path.exists(extracted):
                os.rename(extracted, dest)

        os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
                 stat.S_IROTH | stat.S_IXOTH)
        try:
            os.remove(archive)
        except OSError:
            pass
        return dest
