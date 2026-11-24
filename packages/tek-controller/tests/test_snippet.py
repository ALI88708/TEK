"""Controller -> snippet -> RUNTIME round trip.

The generated Kaggle cell is actually executed against the real tek_runtime package
(with `main` replaced by a recorder), so we prove the Controller's config produces the
exact GuestConfig the runtime expects."""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tek-controller"))
sys.path.insert(0, str(ROOT / "tek-runtime"))
from tek_controller.snippet import build_notebook_snippet, validate_config

SHA = "ab" * 32


def _run(snippet, monkeypatch):
    import tek_runtime
    seen = {}
    monkeypatch.setattr(tek_runtime, "main", lambda guest=None, **k: seen.setdefault("guest", guest))
    exec(compile(snippet, "<snippet>", "exec"), {})
    return seen["guest"]


def test_alpine_default(monkeypatch):
    s = build_notebook_snippet({"iso_type": "alpine", "display_name": "Alpine Linux"})
    ast.parse(s)
    g = _run(s, monkeypatch)
    assert g.iso.url == "alpine" and g.firmware == "bios" and g.machine == "pc" and g.disk_size_gb == 0


def test_url_full_round_trip(monkeypatch):
    cfg = {"iso_type": "url", "iso_value": "https://example.com/os.iso", "sha256": SHA.upper(),
           "display_name": "Debian 12", "disk_size_gb": 10.0, "vcpu": 2, "ram_mb": 2048,
           "firmware": "uefi", "machine": "q35"}
    g = _run(build_notebook_snippet(cfg), monkeypatch)
    assert (g.iso.url, g.iso.sha256, g.display_name) == ("https://example.com/os.iso", SHA, "Debian 12")
    assert (g.vcpu, g.ram_mb, g.disk_size_gb, g.firmware, g.machine) == (2, 2048, 10.0, "uefi", "q35")


def test_local_path_round_trip(monkeypatch):
    cfg = {"iso_type": "path", "iso_value": "/kaggle/input/ds/os.iso", "display_name": "FreeBSD"}
    g = _run(build_notebook_snippet(cfg), monkeypatch)
    assert g.iso.path == "/kaggle/input/ds/os.iso" and g.display_name == "FreeBSD"


def test_quotes_in_values_cannot_break_the_snippet(monkeypatch):
    cfg = {"iso_type": "path", "iso_value": "/kaggle/input/it's \"odd\".iso", "display_name": "O'Brien \"OS\""}
    g = _run(build_notebook_snippet(cfg), monkeypatch)
    assert g.iso.path == cfg["iso_value"] and g.display_name == cfg["display_name"]


@pytest.mark.parametrize("bad, msg", [
    ({"iso_type": "url", "iso_value": "ftp://x/y.iso"}, "http"),
    ({"iso_type": "url", "iso_value": "https://a b/c.iso"}, "http"),
    ({"iso_type": "path", "iso_value": ""}, "path"),
    ({"iso_type": "alpine", "sha256": "xyz"}, "SHA-256"),
    ({"iso_type": "alpine", "firmware": "coreboot"}, "Firmware"),
    ({"iso_type": "alpine", "machine": "vbox"}, "Machine"),
    ({"iso_type": "alpine", "ram_mb": 100}, "ram_mb"),
    ({"iso_type": "floppy"}, "ISO source"),
])
def test_invalid_configs_are_rejected_with_clear_message(bad, msg):
    with pytest.raises(ValueError, match=msg):
        validate_config(bad)


def test_snippet_contains_no_secret_material():
    s = build_notebook_snippet({"iso_type": "alpine"})
    for word in ("SECRET", "TOKEN", "password"):
        assert word.lower() not in s.lower()
