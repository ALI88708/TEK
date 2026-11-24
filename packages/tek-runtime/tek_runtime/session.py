"""TEK Runtime session — generic VM orchestration.

Supports any ISO via GuestConfig/IsoSpec.
Alpine is just the default when no config is provided.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

from . import deps, display, qemu, tunnel
from .authproxy import AuthProxy
from .control import make_descriptor
from .crypto import pairing_nonce, vnc_password
from .detect import summary as detect_summary
from .disk import DiskSpec, create as create_disk, default_path as default_disk_path
from .guest_config import GuestConfig
from .iso_manager import IsoSpec, prepare as prepare_iso
from .plan import make_plan
from .watchdog import ProcessWatchdog, ServiceConfig, RestartPolicy


class SessionAlreadyRunning(RuntimeError):
    """Raised when start() is called while a session is already live."""


_active_session: "TekSession | None" = None


class TekSession:
    def __init__(
        self,
        secret: bytes,
        guest: "GuestConfig | None" = None,
        *,
        iso_path: str | None = None,       # pre-v8 API, kept for backward compatibility
    ) -> None:
        if guest is None and iso_path:
            guest = GuestConfig.from_local(iso_path)
        self.secret           = secret
        self._guest           = guest     # None → Alpine default on start
        self.session_id:  str = ""
        self.tunnel_url:  str = ""
        self.descriptor_json: str = ""
        self._proxy: AuthProxy | None = None
        self._stop = threading.Event()
        self._started     = False
        self._watchdog: "ProcessWatchdog | None" = None
        self._iso_path:  str = ""
        self._disk_path: str | None = None

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        global _active_session
        if _active_session is not None and _active_session._started:
            raise SessionAlreadyRunning(
                "A TEK session is already running in this process.\n"
                "Call tek_runtime.stop_active_session() first, "
                "or restart the Kaggle kernel."
            )
        try:
            self._do_start()
        except Exception:
            self._do_stop(quiet=True)
            raise
        _active_session = self
        self._started = True

    def _do_start(self) -> None:
        # 1. Detect resources
        print("=== TEK: detecting resources ===")
        facts = detect_summary()
        print(
            f"  CPU {facts['cpu']} vCPU | "
            f"RAM {facts['ram_bytes'] // (1024**3):.1f} GB | "
            f"Disk {facts['disk_free_bytes'] // (1024**3):.1f} GB | "
            f"KVM {'yes ✓' if facts['has_kvm'] else 'no — TCG mode'}"
        )

        # 2. Plan resources
        plan = make_plan(facts["cpu"], facts["ram_bytes"], facts["disk_free_bytes"])
        for w in plan.warnings:
            print(f"  WARN: {w}")

        # Resolve per-guest CPU/RAM overrides and validate them BEFORE downloading anything
        guest = self._guest
        vcpu   = (guest.vcpu  if guest and guest.vcpu  else None) or plan.vcpu
        ram_mb = (guest.ram_mb if guest and guest.ram_mb else None) or plan.ram_mb
        if vcpu > facts["cpu"]:
            raise ValueError(
                f"Requested {vcpu} vCPU but this host only has {facts['cpu']}."
            )
        if ram_mb > plan.ram_mb:
            raise ValueError(
                f"Requested {ram_mb} MB RAM but only {plan.ram_mb} MB is available "
                "to the guest after the host reserve."
            )
        if guest and guest.disk_size_gb > plan.disk_gb:
            raise ValueError(
                f"Requested {guest.disk_size_gb:.0f} GB virtual disk but only "
                f"{plan.disk_gb:.1f} GB of scratch space is available after headroom "
                "(the ISO also needs space)."
            )
        print(f"  Guest plan → {vcpu} vCPU | {ram_mb} MB RAM | {plan.disk_gb:.1f} GB disk")

        # 3. Dependencies
        print("=== TEK: installing dependencies ===")
        deps.install_all()

        # 4. ISO — generic engine, no Alpine assumption
        print("=== TEK: preparing ISO ===")
        if guest is None:
            # Default: Alpine Linux test image
            iso_spec = IsoSpec.alpine()
            guest = GuestConfig(iso=iso_spec, display_name="Alpine Linux")
            self._guest = guest
        self._iso_path = prepare_iso(guest.iso)
        print(f"  ISO: {self._iso_path}")

        # 5. Virtual disk (optional)
        if guest.disk_path:
            self._disk_path = guest.disk_path
            print(f"  Disk (pre-existing): {self._disk_path}")
        elif guest.disk_size_gb > 0:
            print("=== TEK: creating virtual disk ===")
            dspec = DiskSpec(
                path=default_disk_path(
                    f"sess-{int(time.time())}",
                    cache_dir="/kaggle/temp" if __import__("os").path.isdir("/kaggle/temp") else "/tmp",
                ),
                size_gb=guest.disk_size_gb,
            )
            self._disk_path = create_disk(dspec)
            self._guest.disk_path = self._disk_path  # update for watchdog info

        # 6. QEMU
        print("=== TEK: starting QEMU ===")
        vnc_pw = vnc_password(self.secret)
        qemu.start(
            self._iso_path,
            vcpu, ram_mb, vnc_pw,
            disk_path=self._disk_path,
            machine=guest.machine,
            boot_order=guest.boot_order,
            firmware=guest.firmware,
            extra_args=guest.extra_qemu_args or None,
        )
        print("  QEMU started.")

        # 7. Display bridge — bind to the VNC port QEMU REALLY chose (not assumed 5900)
        print("=== TEK: starting display bridge ===")
        vnc_port = qemu.get_vnc_port()
        if vnc_port is None:
            raise RuntimeError(
                "Could not determine QEMU's VNC port from the monitor (`info vnc`)."
            )
        qemu.wait_vnc_ready(vnc_port)
        print(f"  QEMU VNC server answering on 127.0.0.1:{vnc_port}.")
        display.start(vnc_port)
        print(f"  websockify 127.0.0.1:6081 -> VNC {vnc_port}.")

        # 8. Auth proxy
        print("=== TEK: starting auth proxy ===")
        self._proxy = AuthProxy(secret=self.secret)
        self._proxy.start()

        # 9. Tunnel
        print("=== TEK: opening Cloudflare tunnel ===")
        self.tunnel_url = tunnel.start()
        host = urlsplit(self.tunnel_url).hostname or ""

        # 10. Descriptor
        self.session_id, self.descriptor_json = make_descriptor(
            self.secret, self.tunnel_url, plan.as_dict(),
            guest_os=guest.display_name or "Guest OS",
        )

        # 11. Publish atomically
        self._proxy.mark_ready(self.session_id, self.descriptor_json, host)

        # 12. Watchdog
        self._watchdog = self._build_watchdog()
        self._watchdog.start()
        print("  Watchdog active.")

        # 13. Print connection info
        nonce = pairing_nonce(self.secret)
        print()
        print("=" * 60)
        print("  TEK READY")
        print(f"  host = {host}")
        print(f"  pair = {nonce}")
        print(f"  guest = {guest.display_name}")
        if self._disk_path:
            print(f"  disk = {self._disk_path}")
            print("  NOTE: disk is temporary — lost when Kaggle session ends")
        print("=" * 60)
        print()

    # ------------------------------------------------------------------ #

    def _build_watchdog(self) -> ProcessWatchdog:
        def _on_dead(name: str) -> None:
            print(f"[Watchdog] {name} DEAD — shutting down session.")
            self._stop.set()

        wd = ProcessWatchdog(check_interval_s=15, on_dead=_on_dead)
        wd.register(ServiceConfig(
            name="qemu", is_alive=qemu.is_alive,
            start_fn=lambda: None, policy=RestartPolicy.NEVER,
        ))
        wd.register(ServiceConfig(
            name="display", is_alive=display._port_open,
            start_fn=display.start, policy=RestartPolicy.ON_FAILURE,
            max_restarts=3,
        ))
        wd.register(ServiceConfig(
            name="tunnel",
            is_alive=lambda: tunnel._proc is not None and tunnel._proc.poll() is None,
            start_fn=lambda: setattr(self, "tunnel_url", tunnel.start()),
            policy=RestartPolicy.ON_FAILURE, max_restarts=5,
        ))
        return wd

    def wait(self) -> None:
        try:
            while not self._stop.is_set():
                if not qemu.is_alive():
                    print("TEK: QEMU stopped. Shutting down.")
                    break
                time.sleep(15)
        except KeyboardInterrupt:
            print("\nTEK: interrupt received.")
        finally:
            self.stop()

    def stop(self) -> None:
        self._do_stop(quiet=False)

    def _do_stop(self, quiet: bool = False) -> None:
        global _active_session
        if not quiet:
            print("=== TEK: stopping ===")
        if self._watchdog:
            self._watchdog.stop()
            self._watchdog = None
        qemu.stop()
        display.stop()
        tunnel.stop()
        if self._proxy:
            self._proxy.stop()
            self._proxy = None
        self._started = False
        if _active_session is self:
            _active_session = None
        if not quiet:
            print("=== TEK: stopped ===")


def stop_active_session() -> None:
    global _active_session
    if _active_session is not None:
        _active_session.stop()
    else:
        print("No active TEK session.")
