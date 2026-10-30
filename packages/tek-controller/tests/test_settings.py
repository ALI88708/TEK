"""Settings persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tek_controller.settings import Settings, load_settings, save_settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.fit_display is True
    assert settings.scale_percent == 100
    assert settings.show_grid is True
    assert settings.connect_timeout_s == 30
    assert settings.verify_expiry is True


def test_missing_file_yields_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "absent.json") == Settings()


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(
        fit_display=False,
        scale_percent=125,
        show_grid=False,
        connect_timeout_s=45,
        verify_expiry=False,
        remembered_host="example-words.trycloudflare.com",
    )
    save_settings(original, path)

    assert load_settings(path) == original


def test_corrupt_file_yields_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_directory_instead_of_file_yields_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path) == Settings()


def test_unreadable_file_yields_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    def deny(*_args: object, **_kwargs: object) -> str:
        raise PermissionError("simulated denial")

    monkeypatch.setattr(Path, "read_text", deny)
    assert load_settings(path) == Settings()


def test_failed_save_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("tek_controller.settings.os.replace", fail)

    with pytest.raises(OSError):
        save_settings(Settings(), path)

    assert list(tmp_path.iterdir()) == []


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"scale_percent": 125, "mystery": True}), encoding="utf-8")
    assert load_settings(path).scale_percent == 125


def test_out_of_range_values_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"scale_percent": 999, "connect_timeout_s": -5}),
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.scale_percent == 100
    assert loaded.connect_timeout_s == 30


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(Settings(), path)
    assert path.exists()
    assert list(tmp_path.iterdir()) == [path]


def test_settings_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "settings.json"
    save_settings(Settings(), path)
    assert path.exists()
