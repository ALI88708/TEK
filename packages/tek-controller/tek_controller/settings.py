"""Local controller preferences.

Small, boring, and tolerant: a corrupt or partial file falls back to defaults
rather than blocking startup.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCALE_CHOICES: tuple[int, ...] = (75, 100, 125, 150)
TIMEOUT_MIN_S = 5
TIMEOUT_MAX_S = 120


@dataclass(frozen=True, slots=True)
class Settings:
    fit_display: bool = True
    scale_percent: int = 100
    show_grid: bool = True
    connect_timeout_s: int = 30
    verify_expiry: bool = True
    remembered_host: str = ""


def default_settings_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / "TEK" / "controller.json"
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "tek" / "controller.json"


def _coerce_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_choice(value: Any, choices: tuple[int, ...], default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value in choices:
        return value
    return default


def _coerce_timeout(value: Any, default: int) -> int:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and TIMEOUT_MIN_S <= value <= TIMEOUT_MAX_S
    ):
        return value
    return default


def _coerce_text(value: Any, default: str) -> str:
    if isinstance(value, str):
        return value.strip()[:255]
    return default


def load_settings(path: Path | str | None = None) -> Settings:
    target = Path(path) if path is not None else default_settings_path()

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return Settings()

    if not isinstance(raw, dict):
        return Settings()

    defaults = Settings()
    return Settings(
        fit_display=_coerce_bool(raw.get("fit_display"), defaults.fit_display),
        scale_percent=_coerce_choice(
            raw.get("scale_percent"), SCALE_CHOICES, defaults.scale_percent
        ),
        show_grid=_coerce_bool(raw.get("show_grid"), defaults.show_grid),
        connect_timeout_s=_coerce_timeout(
            raw.get("connect_timeout_s"), defaults.connect_timeout_s
        ),
        verify_expiry=_coerce_bool(raw.get("verify_expiry"), defaults.verify_expiry),
        remembered_host=_coerce_text(
            raw.get("remembered_host"), defaults.remembered_host
        ),
    )


def save_settings(settings: Settings, path: Path | str | None = None) -> Path:
    target = Path(path) if path is not None else default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    handle, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=".settings-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(asdict(settings), stream, indent=2)
            stream.write("\n")
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise

    return target
