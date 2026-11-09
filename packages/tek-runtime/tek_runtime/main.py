"""Kaggle notebook entry point. Reads TEK_SESSION_SECRET; never generates it."""
from __future__ import annotations

import os


def main(iso_path: str | None = None) -> None:
    """Call this from a Kaggle notebook cell after setting TEK_SESSION_SECRET."""
    from .crypto import secret_from_env
    from .session import TekSession

    env_val = os.environ.get("TEK_SESSION_SECRET", "")
    if not env_val:
        raise RuntimeError(
            "TEK_SESSION_SECRET is not set.\n"
            "Set it in a Kaggle secret or in a private cell above this one.\n"
            "TEK never generates or prints the secret."
        )

    secret = secret_from_env(env_val)
    session = TekSession(iso_path=iso_path, secret=secret)
    session.start()
    session.wait()
