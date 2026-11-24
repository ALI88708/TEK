"""Kaggle notebook entry point.

    from tek_runtime import main, GuestConfig

    main()                                   # default test image (Alpine)
    main(guest=GuestConfig.from_url(
        "https://example.com/os.iso", sha256="<hex>", name="My OS", disk_size_gb=10))
    main(guest=GuestConfig.from_local("/kaggle/input/ds/os.iso", name="My OS"))
    main(iso_path="/kaggle/input/ds/os.iso")  # backward-compatible shorthand

    from tek_runtime import stop_active_session; stop_active_session()
"""
from __future__ import annotations

import os


def main(guest=None, *, iso_path: str | None = None) -> None:
    """Start a TEK session and block until it ends.

    `guest` (GuestConfig) takes precedence. `iso_path` is kept for backward
    compatibility with notebooks written before v8.
    TEK_SESSION_SECRET must be set as a Kaggle Secret.
    """
    from .crypto import secret_from_env
    from .guest_config import GuestConfig
    from .session import SessionAlreadyRunning, TekSession

    env_val = os.environ.get("TEK_SESSION_SECRET", "")
    if not env_val:
        raise RuntimeError(
            "TEK_SESSION_SECRET is not set.\n"
            "Add it via Add-ons -> Secrets -> New Secret (name: TEK_SESSION_SECRET)."
        )
    try:
        secret = secret_from_env(env_val)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    if guest is None and iso_path:
        guest = GuestConfig.from_local(iso_path)

    session = TekSession(secret=secret, guest=guest)
    try:
        session.start()
        session.wait()
    except SessionAlreadyRunning as exc:
        print(f"\n[TEK] {exc}")
        print("[TEK] To stop: from tek_runtime import stop_active_session; stop_active_session()")
