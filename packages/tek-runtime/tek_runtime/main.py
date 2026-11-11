"""Kaggle notebook entry point.

Usage:
    from tek_runtime import main
    main()          # TEK_SESSION_SECRET must be set

    # To stop from another cell:
    from tek_runtime import stop_active_session
    stop_active_session()
"""
from __future__ import annotations

import os


def main(iso_path: str | None = None) -> None:
    """Start a TEK session. Blocks until the session ends.

    Set TEK_SESSION_SECRET as a Kaggle Secret (never print it).
    """
    from .crypto import secret_from_env
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

    session = TekSession(iso_path=iso_path, secret=secret)
    try:
        session.start()
        session.wait()
    except SessionAlreadyRunning as exc:
        print(f"\n[TEK] {exc}")
        print("[TEK] To stop the current session:")
        print("        from tek_runtime import stop_active_session")
        print("        stop_active_session()")
