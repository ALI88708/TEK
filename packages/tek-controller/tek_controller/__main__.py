"""Entry point: ``python -m tek_controller``."""

from __future__ import annotations

import argparse
import tkinter as tk
from collections.abc import Sequence
from pathlib import Path

from tek_controller import __version__, theme
from tek_controller.app import VIEW_META, TekControllerApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tek-controller",
        description="Desktop controller for a temporary TEK environment on Kaggle.",
    )
    parser.add_argument(
        "--view",
        choices=sorted(VIEW_META),
        default="dashboard",
        help="view to open at startup (default: dashboard)",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=None,
        help="override the settings file location",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="open the window, run the event loop briefly, then exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tek-controller {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    theme.enable_windows_dpi_awareness()
    root = tk.Tk()
    app = TekControllerApp(root, settings_path=args.settings)
    app.show_view(args.view)

    if args.smoke:
        root.after(900, app.close)
        root.mainloop()
        print("smoke ok: window opened and the event loop ran")
        return 0

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
