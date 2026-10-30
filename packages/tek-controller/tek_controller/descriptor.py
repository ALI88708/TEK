"""Parsing and validation for the TEK session descriptor (protocol ``tek/0``).

Pure functions: no Tk, no network, no filesystem. Mirrors ``docs/protocol.md``
section 4 and never echoes a URL, token, or password back in an error message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

SUPPORTED_PROTOCOL = "tek/0"
SUPPORTED_SCHEMA = "tek.session.v0"
GUEST_STATES = frozenset({"booting", "ready", "stopped", "failed"})

CREDENTIAL_PARAMETERS = frozenset(
    {
        "token",
        "auth",
        "access_token",
        "id_token",
        "password",
        "passwd",
        "key",
        "api_key",
        "secret",
        "sig",
        "signature",
    }
)


class DescriptorError(ValueError):
    """A validation failure with a stable code and a credential-free message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DisplayInfo:
    transport: str
    url: str
    password_scheme: str
    geometry: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ResourceInfo:
    vcpu: int
    ram_mb: int
    disk_gb: float


@dataclass(frozen=True, slots=True)
class GuestInfo:
    os: str
    state: str


@dataclass(frozen=True, slots=True)
class SessionDescriptor:
    schema: str
    protocol: str
    session_id: str
    created_at: str
    expires_at: str
    runtime_version: str
    secret_fingerprint: str
    display: DisplayInfo
    resources: ResourceInfo
    guest: GuestInfo

    def summary(self) -> str:
        width, height = self.display.geometry
        return (
            f"{self.protocol} | {self.session_id} | "
            f"{self.display.transport} {width}x{height} | "
            f"guest {self.guest.os}/{self.guest.state}"
        )


def _as_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise DescriptorError("EMPTY_DESCRIPTOR", "Paste a session descriptor to continue.")

    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DescriptorError(
            "INVALID_JSON",
            f"Descriptor is not valid JSON (line {exc.lineno}, column {exc.colno}).",
        ) from None

    if not isinstance(body, dict):
        raise DescriptorError("INVALID_DESCRIPTOR", "Descriptor must be a JSON object.")
    return body


def _require_text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DescriptorError("MISSING_FIELD", f"Descriptor is missing the field '{key}'.")
    return value


def _require_object(body: dict[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise DescriptorError("MISSING_FIELD", f"Descriptor is missing the object '{key}'.")
    return value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_timestamp(value: str, field: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise DescriptorError(
            "INVALID_TIMESTAMP", f"Field '{field}' is not an ISO-8601 timestamp."
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _validate_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        raise DescriptorError(
            "INVALID_FIELD", "The display URL is not a valid URL."
        ) from None

    if parts.scheme.lower() != "https":
        raise DescriptorError("INSECURE_TRANSPORT", "The display URL must use https.")

    if "@" in parts.netloc or parts.username or parts.password:
        raise DescriptorError(
            "CREDENTIAL_IN_URL", "The display URL must not embed credentials."
        )

    if not parts.hostname:
        raise DescriptorError("INVALID_FIELD", "The display URL has no host.")

    for name, _ in parse_qsl(parts.query, keep_blank_values=True):
        if name.lower() in CREDENTIAL_PARAMETERS:
            raise DescriptorError(
                "CREDENTIAL_IN_URL",
                "The display URL must not carry credentials in the query string.",
            )

    for name, _ in parse_qsl(parts.fragment, keep_blank_values=True):
        if name.lower() in CREDENTIAL_PARAMETERS:
            raise DescriptorError(
                "CREDENTIAL_IN_URL",
                "The display URL must not carry credentials in the fragment.",
            )

    return url


def _parse_geometry(value: Any) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise DescriptorError("INVALID_FIELD", "display.geometry must be [width, height].")

    width, height = value
    if not (_is_int(width) and _is_int(height) and width > 0 and height > 0):
        raise DescriptorError(
            "INVALID_FIELD", "display.geometry must contain positive integers."
        )
    return int(width), int(height)


def parse_descriptor(
    raw: str,
    *,
    now: datetime | None = None,
    check_expiry: bool = True,
) -> SessionDescriptor:
    """Validate a descriptor and return an immutable view of it."""
    body = _as_object(raw)

    protocol = _require_text(body, "protocol")
    if protocol != SUPPORTED_PROTOCOL:
        raise DescriptorError(
            "UNSUPPORTED_PROTOCOL",
            f"Unsupported protocol. This build speaks {SUPPORTED_PROTOCOL}.",
        )

    schema = body.get("schema")
    if schema is not None and schema != SUPPORTED_SCHEMA:
        raise DescriptorError(
            "UNSUPPORTED_SCHEMA", f"Unsupported schema. Expected {SUPPORTED_SCHEMA}."
        )

    session_id = _require_text(body, "session_id")
    created_at = _require_text(body, "created_at")
    expires_at = _require_text(body, "expires_at")
    runtime_version = _require_text(body, "runtime_version")
    secret_fingerprint = _require_text(body, "secret_fingerprint")

    display_body = _require_object(body, "display")
    transport = _require_text(display_body, "transport")
    url = _validate_url(_require_text(display_body, "url"))
    password_scheme = _require_text(display_body, "password_scheme")
    geometry = _parse_geometry(display_body.get("geometry"))

    resources_body = _require_object(body, "resources")
    vcpu = resources_body.get("vcpu")
    ram_mb = resources_body.get("ram_mb")
    disk_gb = resources_body.get("disk_gb")
    if not (isinstance(vcpu, int) and not isinstance(vcpu, bool) and vcpu > 0):
        raise DescriptorError("INVALID_FIELD", "resources.vcpu must be a positive integer.")
    if not (isinstance(ram_mb, int) and not isinstance(ram_mb, bool) and ram_mb > 0):
        raise DescriptorError("INVALID_FIELD", "resources.ram_mb must be a positive integer.")
    if not isinstance(disk_gb, (int, float)) or isinstance(disk_gb, bool) or disk_gb <= 0:
        raise DescriptorError("INVALID_FIELD", "resources.disk_gb must be a positive number.")

    guest_body = _require_object(body, "guest")
    guest_os = _require_text(guest_body, "os")
    guest_state = _require_text(guest_body, "state")
    if guest_state not in GUEST_STATES:
        raise DescriptorError(
            "INVALID_FIELD",
            "guest.state must be one of: " + ", ".join(sorted(GUEST_STATES)) + ".",
        )

    created = _parse_timestamp(created_at, "created_at")
    expires = _parse_timestamp(expires_at, "expires_at")

    if check_expiry:
        reference = now or datetime.now(UTC)
        if expires <= reference:
            raise DescriptorError(
                "AUTH_EXPIRED", "Descriptor has expired. Request a fresh one from the runtime."
            )

    if expires <= created:
        raise DescriptorError(
            "INVALID_TIMESTAMP", "expires_at must be later than created_at."
        )

    return SessionDescriptor(
        schema=schema or SUPPORTED_SCHEMA,
        protocol=protocol,
        session_id=session_id,
        created_at=created_at,
        expires_at=expires_at,
        runtime_version=runtime_version,
        secret_fingerprint=secret_fingerprint,
        display=DisplayInfo(
            transport=transport,
            url=url,
            password_scheme=password_scheme,
            geometry=geometry,
        ),
        resources=ResourceInfo(vcpu=vcpu, ram_mb=ram_mb, disk_gb=float(disk_gb)),
        guest=GuestInfo(os=guest_os, state=guest_state),
    )
