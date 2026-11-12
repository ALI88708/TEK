"""Kaggle notebook entry point.

Usage:
    # Minimal — Alpine Linux auto-downloaded
    from tek_runtime import main
    main()

    # Custom ISO
    from tek_runtime import main
    main(iso_path="/kaggle/input/my-dataset/ubuntu.iso")

    # Full control
    from tek_runtime import main
    from tek_runtime.guest_config import GuestConfig
    main(guest=GuestConfig.for_custom_linux("/path/to/debian.iso", "Debian 12"))

    # Stop from another cell (while session.wait() is blocking above)
    from tek_runtime import stop_active_session
    stop_active_session()

TEK_SESSION_SECRET must be set as a Kaggle Secret. Never print it.
"""
from __future__ import annotations

import os


def main(
    iso_path: str | None = None,
    guest=None,            # GuestConfig | None — avoids import at module level
) -> None:
    """Start a TEK session and block until it ends.

    Parameters
    ----------
    iso_path
        Path to a guest OS ISO. Ignored when `guest` is provided.
        If neither is given, Alpine Linux is auto-downloaded.
    guest
        A GuestConfig instance for full control over the guest OS and
        QEMU settings. Takes precedence over `iso_path`.
    """
    from .crypto import secret_from_env
    from .guest_config import GuestConfig
    from .session import TekSession, SessionAlreadyRunning

    env_val = os.environ.get("TEK_SESSION_SECRET", "")
    if not env_val:
        raise RuntimeError(
            "TEK_SESSION_SECRET is not set.\n"
            "Add it via Add-ons → Secrets → New Secret (name: TEK_SESSION_SECRET).\n"
            "TEK never generates or prints the secret."
        )

    try:
        secret = secret_from_env(env_val)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    # Build GuestConfig if not provided
    if guest is None and iso_path is not None:
        guest = GuestConfig.for_custom_linux(iso_path)

    session = TekSession(secret=secret, guest=guest)
    try:
        session.start()
        session.wait()
    except SessionAlreadyRunning as exc:
        print(f"\n[TEK] {exc}")
        print("[TEK] To stop the current session:")
        print("        from tek_runtime import stop_active_session")
        print("        stop_active_session()")
