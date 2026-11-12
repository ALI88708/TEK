"""TEK Runtime session: orchestration + state machine.

Idempotency guarantees:
  - A module-level _active_session guards against creating two sessions in
    the same Python process (notebook cell re-run). If called a second time
    while a session is live, start() raises SessionAlreadyRunning.
  - display.start() and tunnel.start() are idempotent — they skip startup if
    their respective port / URL is already up.

Cleanup guarantee:
  - If start() fails at any step, it calls stop() before re-raising so it
    never leaves orphaned processes.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

from . import deps, display, fetch_iso, qemu, tunnel
from .guest_config import GuestConfig
from .authproxy import AuthProxy
from .control import make_descriptor
from .crypto import (
    auth_token,
    pairing_nonce,
    vnc_password,
)
from .detect import summary as detect_summary
from .plan import make_plan


class SessionAlreadyRunning(RuntimeError):
    """Raised when start() is called while a session is already live."""


# Module-level singleton — prevents duplicate sessions in one process.
_active_session: "TekSession | None" = None


class TekSession:
    def __init__(
        self,
        secret: bytes,
        iso_path: str | None = None,
        guest: GuestConfig | None = None,
    ) -> None:
        # guest takes precedence over bare iso_path
        self.secret           = secret
        self._guest           = guest
        self.iso_path         = guest.iso_path if guest else iso_path
        self.session_id:  str = ""
        self.tunnel_url:  str = ""
        self.descriptor_json: str = ""
        self._proxy: AuthProxy | None = None
        self._stop = threading.Event()
        self._started = False

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
            # Clean up whatever was started before re-raising.
            self._do_stop(quiet=True)
            raise

        _active_session = self
        self._started = True

    def _do_start(self) -> None:
        # 1. Detect
        print("=== TEK: detecting resources ===")
        facts = detect_summary()
        print(
            f"  CPU {facts['cpu']} vCPU | "
            f"RAM {facts['ram_bytes'] // (1024**3):.1f} GB | "
            f"Disk {facts['disk_free_bytes'] // (1024**3):.1f} GB | "
            f"KVM {'yes ✓' if facts['has_kvm'] else 'no — TCG mode'}"
        )

        # 2. Plan
        plan = make_plan(facts["cpu"], facts["ram_bytes"], facts["disk_free_bytes"])
        for w in plan.warnings:
            print(f"  WARN: {w}")
        print(
            f"  Guest plan → {plan.vcpu} vCPU | "
            f"{plan.ram_mb} MB RAM | {plan.disk_gb:.1f} GB disk"
        )

        # 3. Dependencies
        print("=== TEK: installing dependencies ===")
        deps.install_all()

        # 4. ISO
        if not self.iso_path:
            print("=== TEK: fetching ISO ===")
            self.iso_path = fetch_iso.get_alpine()

        # 5. QEMU
        print("=== TEK: starting QEMU ===")
        vnc_pw = vnc_password(self.secret)
        g = self._guest
        qemu.start(
            self.iso_path,
            plan.vcpu,
            plan.ram_mb,
            vnc_pw,
            disk_path=g.disk_path if g else None,
            machine=g.machine if g else "pc",
            boot_order=g.boot_order if g else "d",
            extra_args=g.extra_qemu_args if g else None,
        )
        print("  QEMU started.")

        # 6. Display bridge (idempotent)
        print("=== TEK: starting display bridge ===")
        display.start()
        print("  websockify ready on 127.0.0.1:6081.")

        # 7. Auth proxy — starts NOT ready; mark_ready() called after tunnel
        print("=== TEK: starting auth proxy ===")
        self._proxy = AuthProxy(secret=self.secret)
        self._proxy.start()

        # 8. Tunnel (idempotent — reuses existing URL if already up)
        print("=== TEK: opening Cloudflare tunnel ===")
        self.tunnel_url = tunnel.start()
        host = urlsplit(self.tunnel_url).hostname or ""

        # 9. Descriptor
        self.session_id, self.descriptor_json = make_descriptor(
            self.secret, self.tunnel_url, plan.as_dict()
        )

        # 10. Atomically publish — unblocks auth endpoints
        self._proxy.mark_ready(self.session_id, self.descriptor_json, host)

        # 11. Print connection info (no secret, no token, no descriptor)
        nonce = pairing_nonce(self.secret)
        print()
        print("=" * 60)
        print("  TEK READY")
        print(f"  host = {host}")
        print(f"  pair = {nonce}")
        print("=" * 60)
        print()
        print("  In TEK Controller:")
        print(f"    1. Verify pair code matches: {nonce}")
        print(f"    2. Tunnel host: {host}")
        print("    3. Click 'Fetch & Connect' → 'Open Display'")
        print()
        print("=" * 60)
        print()

    # ------------------------------------------------------------------ #

    def wait(self) -> None:
        try:
            while not self._stop.is_set():
                if not qemu.is_alive():
                    print("TEK: QEMU stopped responding. Shutting down.")
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
    """Stop the currently running session from a notebook cell."""
    global _active_session
    if _active_session is not None:
        _active_session.stop()
    else:
        print("No active TEK session.")
