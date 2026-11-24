"""Build the Kaggle notebook cell that starts the VM chosen in the Controller.

The Controller cannot launch a Kaggle notebook by itself (no Kaggle launch API is
implemented here), so the honest flow is: configure here -> copy this snippet ->
paste it into the TEK notebook's last cell on Kaggle -> run it.
"""
from __future__ import annotations

import re

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
ISO_TYPES = ("alpine", "url", "path")


def validate_config(config: dict) -> None:
    """Raise ValueError with a user-readable message if `config` is unusable."""
    iso_type = config.get("iso_type")
    if iso_type not in ISO_TYPES:
        raise ValueError(f"ISO source must be one of {ISO_TYPES}.")
    value = str(config.get("iso_value", "")).strip()
    if iso_type == "url":
        if not re.match(r"^https?://\S+$", value):
            raise ValueError("ISO URL must start with http:// or https:// and contain no spaces.")
    elif iso_type == "path" and not value:
        raise ValueError("Enter the ISO file path on Kaggle (e.g. /kaggle/input/<dataset>/os.iso).")
    sha = str(config.get("sha256", "")).strip()
    if sha and not _SHA256.match(sha):
        raise ValueError("SHA-256 must be exactly 64 hexadecimal characters (or empty).")
    if float(config.get("disk_size_gb", 0) or 0) < 0:
        raise ValueError("Disk size cannot be negative.")
    if config.get("firmware", "bios") not in ("bios", "uefi"):
        raise ValueError("Firmware must be BIOS or UEFI.")
    if config.get("machine", "pc") not in ("pc", "q35"):
        raise ValueError("Machine type must be pc or q35.")
    for key, low in (("vcpu", 1), ("ram_mb", 256)):
        v = config.get(key)
        if v is not None and int(v) < low:
            raise ValueError(f"{key} must be at least {low} (or left on Auto).")


def build_notebook_snippet(config: dict) -> str:
    """Return Python source for the notebook cell. Raises ValueError on bad config."""
    validate_config(config)
    iso_type = config["iso_type"]
    value = str(config.get("iso_value", "")).strip()
    sha = str(config.get("sha256", "")).strip().lower()
    name = str(config.get("display_name", "")).strip() or "Guest OS"

    if iso_type == "alpine":
        iso = "IsoSpec.alpine()"
    elif iso_type == "url":
        iso = f"IsoSpec.from_url({value!r}" + (f", sha256={sha!r}" if sha else "") + f", name={name!r})"
    else:
        iso = f"IsoSpec.from_path({value!r}" + (f", sha256={sha!r}" if sha else "") + f", name={name!r})"

    args = [f"iso={iso}", f"display_name={name!r}"]
    if config.get("vcpu"):
        args.append(f"vcpu={int(config['vcpu'])}")
    if config.get("ram_mb"):
        args.append(f"ram_mb={int(config['ram_mb'])}")
    if float(config.get("disk_size_gb", 0) or 0) > 0:
        args.append(f"disk_size_gb={float(config['disk_size_gb'])!r}")
    if config.get("firmware", "bios") != "bios":
        args.append(f"firmware={config['firmware']!r}")
    if config.get("machine", "pc") != "pc":
        args.append(f"machine={config['machine']!r}")

    body = ",\n    ".join(args)
    return (
        "from tek_runtime import main, GuestConfig, IsoSpec\n\n"
        f"main(guest=GuestConfig(\n    {body},\n))\n"
    )
