"""TEK Runtime session: orchestration + state machine."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

from . import deps, display, fetch_iso, qemu, tunnel
from .authproxy import AuthProxy
from .control import make_descriptor
from .crypto import (
    auth_token,
    pairing_nonce,
    vnc_password,
)
from .detect import summary as detect_summary
from .plan import make_plan


class TekSession:
    def __init__(self, iso_path: str | None, secret: bytes) -> None:
        self.iso_path = iso_path
        self.secret = secret
        self.session_id: str = ""
        self.tunnel_url: str = ""
        self.descriptor_json: str = ""
        self._proxy: AuthProxy | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        # 1. Detect
        print("=== TEK: detecting resources ===")
        facts = detect_summary()
        print(
            f"  CPU {facts['cpu']} vCPU | "
            f"RAM {facts['ram_bytes'] // (1024**3):.1f} GB | "
            f"Disk {facts['disk_free_bytes'] // (1024**3):.1f} GB | "
            f"KVM {'yes' if facts['has_kvm'] else 'no (TCG)'}"
        )

        # 2. Plan
        plan = make_plan(facts["cpu"], facts["ram_bytes"], facts["disk_free_bytes"])
        for w in plan.warnings:
            print(f"  WARN: {w}")
        print(
            f"  Guest → {plan.vcpu} vCPU | "
            f"{plan.ram_mb} MB RAM | "
            f"{plan.disk_gb:.1f} GB disk"
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
        qemu.start(self.iso_path, plan.vcpu, plan.ram_mb, vnc_pw)
        print("  QEMU started.")

        # 6. Display bridge
        print("=== TEK: starting display bridge ===")
        display.start()
        print("  websockify ready on 127.0.0.1:6081.")

        # 7. Auth proxy (placeholder descriptor until tunnel is up)
        print("=== TEK: starting auth proxy ===")
        self._proxy = AuthProxy(
            secret=self.secret,
            session_id="pending",
            descriptor_json="{}",
            tunnel_host="",
        )
        self._proxy.start()

        # 8. Tunnel
        print("=== TEK: opening Cloudflare tunnel ===")
        self.tunnel_url = tunnel.start()
        host = urlsplit(self.tunnel_url).hostname or ""

        # 9. Descriptor
        plan_dict = plan.as_dict()
        self.session_id, self.descriptor_json = make_descriptor(
            self.secret,
            self.tunnel_url,
            plan_dict,
        )

        # 10. Publish session credentials atomically.
        # mark_ready() sets all three fields under a lock and then
        # flips _ready=True, unblocking the auth endpoints.
        self._proxy.mark_ready(self.session_id, self.descriptor_json, host)

        # 11. Print connection info — no secret, no token, no full descriptor
        nonce = pairing_nonce(self.secret)
        print()
        print("=" * 60)
        print("  TEK READY")
        print(f"  host={host}")
        print(f"  pair={nonce}")
        print("=" * 60)
        print()
        print("  In the controller:")
        print(f"    1. Verify pair code matches: {nonce}")
        print(f"    2. Enter tunnel host: {host}")
        print("    3. Click 'Fetch & Connect'")
        # NOTE: kickoff URL intentionally not printed.
        # The token in the URL would enter browser history and Cloudflare logs.
        # Use the TEK Controller to open the display securely.
        print()
        print("=" * 60)
        print()

    def wait(self) -> None:
        try:
            while not self._stop.is_set():
                if not qemu.is_alive():
                    print("TEK: QEMU stopped responding. Shutting down.")
                    break
                time.sleep(15)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        print("=== TEK: stopping ===")
        qemu.stop()
        display.stop()
        tunnel.stop()
        if self._proxy:
            self._proxy.stop()
        print("=== TEK: stopped ===")
