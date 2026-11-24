"""Generic ISO Engine — no assumptions about which OS is inside the ISO.

Supports:
  1. Local file path   → validate it exists and is a regular file
  2. HTTP/HTTPS URL    → download to cache dir with progress
  3. "alpine" shorthand → delegates to fetch_iso.get_alpine() for convenience

SHA-256 verification is optional but strongly recommended for downloaded ISOs.
The engine never inspects the ISO contents — it treats it as an opaque bootable image.

Design rule: NO Alpine-specific logic lives here.
  Alpine support is implemented in fetch_iso.py and referenced only via the
  "alpine" shorthand path, which the caller opts in to explicitly.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.request
from dataclasses import dataclass, field


@dataclass
class IsoSpec:
    """Specification for a guest OS ISO.

    Exactly one of `path` or `url` must be provided (or use the
    factory methods).  `sha256` is optional but recommended for URLs.
    """
    path:         str   = ""    # local path, e.g. "/kaggle/input/my-iso/ubuntu.iso"
    url:          str   = ""    # HTTP/HTTPS URL to download
    sha256:       str   = ""    # expected hex digest (lowercase); "" = skip check
    display_name: str   = ""    # human label, e.g. "Ubuntu 24.04"

    def __post_init__(self) -> None:
        if not self.path and not self.url:
            raise ValueError(
                "IsoSpec requires either `path` (local file) or `url` (HTTP/HTTPS)."
            )
        if self.url and self.url != "alpine" and not (
            self.url.startswith("http://") or self.url.startswith("https://")
        ):
            raise ValueError(
                f"IsoSpec.url must start with http:// or https:// "
                f"(or 'alpine' for the test image); got: {self.url[:60]}"
            )
        if not self.display_name:
            if self.path:
                self.display_name = os.path.basename(self.path)
            else:
                self.display_name = self.url.split("/")[-1] or "ISO"

    # -- factories --------------------------------------------------------

    @classmethod
    def from_path(cls, path: str, *, sha256: str = "", name: str = "") -> "IsoSpec":
        """Create from a local file path."""
        return cls(path=path, sha256=sha256, display_name=name)

    @classmethod
    def from_url(cls, url: str, *, sha256: str = "", name: str = "") -> "IsoSpec":
        """Create from an HTTP/HTTPS URL."""
        return cls(url=url, sha256=sha256, display_name=name)

    @classmethod
    def alpine(cls) -> "IsoSpec":
        """Convenience spec for the Alpine Linux test image."""
        return cls(url="alpine", display_name="Alpine Linux (default test image)")


class IsoError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message


def prepare(spec: IsoSpec, cache_dir: str | None = None) -> str:
    """Resolve an IsoSpec to a local file path, downloading if needed.

    Returns the absolute path to the ISO file.
    Raises IsoError on any failure.
    """
    # Determine cache directory
    if cache_dir is None:
        cache_dir = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp"

    # ------------------------------------------------------------------ #
    # Case 1: "alpine" shorthand                                           #
    # ------------------------------------------------------------------ #
    if spec.url == "alpine":
        try:
            from .fetch_iso import get_alpine
            return get_alpine(cache_dir=cache_dir)
        except Exception as exc:
            raise IsoError("ALPINE_DOWNLOAD_FAILED", str(exc)) from exc

    # ------------------------------------------------------------------ #
    # Case 2: local path                                                   #
    # ------------------------------------------------------------------ #
    if spec.path:
        path = os.path.abspath(spec.path)
        if not os.path.isfile(path):
            raise IsoError(
                "ISO_NOT_FOUND",
                f"ISO file not found: {path}",
            )
        if os.path.getsize(path) < 1024 * 1024:
            raise IsoError(
                "ISO_TOO_SMALL",
                f"File at {path} is too small to be a valid ISO "
                f"({os.path.getsize(path) // 1024} KB).",
            )
        if spec.sha256:
            _verify_sha256(path, spec.sha256)
        return path

    # ------------------------------------------------------------------ #
    # Case 3: HTTP/HTTPS URL                                               #
    # ------------------------------------------------------------------ #
    filename  = spec.url.split("?")[0].split("/")[-1] or "image.iso"
    dest      = os.path.join(cache_dir, filename)

    if os.path.exists(dest) and os.path.getsize(dest) > 1024 * 1024:
        # Already downloaded — verify hash if provided, then reuse
        print(f"  ISO cached: {dest}  ({os.path.getsize(dest) // (1024**2)} MB)")
        if spec.sha256:
            _verify_sha256_or_discard(dest, spec.sha256)
        return dest

    print(f"  Downloading ISO: {spec.display_name}")
    print(f"  URL: {spec.url}")
    _download(spec.url, dest)

    if spec.sha256:
        _verify_sha256_or_discard(dest, spec.sha256)
    else:
        print("  SHA-256 not provided — skipping integrity check.")

    print(f"  ISO ready: {dest}  ({os.path.getsize(dest) // (1024**2)} MB)")
    return dest


# ---------------------------------------------------------------------- #
# Helpers                                                                  #
# ---------------------------------------------------------------------- #

def _download(url: str, dest: str) -> None:
    """Download URL to dest using curl with retry."""
    r = subprocess.run(
        ["curl", "-fL", "--retry", "3", "--retry-delay", "2",
         "--progress-bar", "-o", dest, url],
        check=False,
    )
    if r.returncode != 0 or not os.path.exists(dest):
        raise IsoError(
            "ISO_DOWNLOAD_FAILED",
            f"Failed to download ISO from {url}. "
            "Check the URL and your network connection.",
        )
    if os.path.getsize(dest) < 1024 * 1024:
        os.remove(dest)
        raise IsoError(
            "ISO_TOO_SMALL",
            f"Downloaded file from {url} is too small to be a valid ISO.",
        )


def _verify_sha256_or_discard(path: str, expected: str) -> None:
    """Verify a file TEK downloaded itself; delete it on mismatch so a retry re-downloads.

    Never used for user-supplied local paths (those are never deleted).
    """
    try:
        _verify_sha256(path, expected)
    except IsoError:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def _verify_sha256(path: str, expected: str) -> None:
    """Compute SHA-256 and raise IsoError if it does not match expected."""
    expected = expected.lower().strip()
    print(f"  Verifying SHA-256 … ", end="", flush=True)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise IsoError(
            "SHA256_MISMATCH",
            f"SHA-256 mismatch for {os.path.basename(path)}.\n"
            f"  Expected: {expected}\n"
            f"  Actual:   {actual}\n"
            "The ISO may be corrupted or tampered with.",
        )
    print("OK")
