"""Descriptor parsing and validation tests (TEK protocol tek/0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tek_controller.descriptor import DescriptorError, parse_descriptor

NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)


def descriptor(**overrides: object) -> str:
    body = {
        "schema": "tek.session.v0",
        "protocol": "tek/0",
        "session_id": "s_01J9Z6K3W7",
        "created_at": "2026-10-30T10:00:00Z",
        "expires_at": "2026-10-30T22:00:00Z",
        "runtime_version": "0.1.0",
        "secret_fingerprint": "9f2c1a7b",
        "display": {
            "transport": "vnc",
            "url": "https://example-words.trycloudflare.com/vnc.html",
            "password_scheme": "hkdf-sha256/v1",
            "geometry": [1280, 800],
        },
        "resources": {"vcpu": 3, "ram_mb": 24576, "disk_gb": 17.5},
        "guest": {"os": "alpine", "state": "ready"},
    }
    body.update(overrides)
    return json.dumps(body)


def expect_code(raw: str, code: str, **kwargs: object) -> DescriptorError:
    with pytest.raises(DescriptorError) as excinfo:
        parse_descriptor(raw, **kwargs)
    assert excinfo.value.code == code
    return excinfo.value


def test_valid_descriptor_is_parsed() -> None:
    parsed = parse_descriptor(descriptor(), now=NOW)

    assert parsed.protocol == "tek/0"
    assert parsed.session_id == "s_01J9Z6K3W7"
    assert parsed.display.transport == "vnc"
    assert parsed.display.geometry == (1280, 800)
    assert parsed.resources.vcpu == 3
    assert parsed.guest.os == "alpine"
    assert parsed.guest.state == "ready"


def test_empty_input_is_rejected() -> None:
    expect_code("   ", "EMPTY_DESCRIPTOR")


def test_invalid_json_is_rejected() -> None:
    expect_code("{not json", "INVALID_JSON")


def test_non_object_json_is_rejected() -> None:
    expect_code("[1, 2, 3]", "INVALID_DESCRIPTOR")


def test_missing_protocol_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    del body["protocol"]
    expect_code(json.dumps(body), "MISSING_FIELD")


def test_unsupported_protocol_is_rejected() -> None:
    expect_code(descriptor(protocol="tek/1"), "UNSUPPORTED_PROTOCOL")


def test_missing_display_url_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    del body["display"]["url"]
    expect_code(json.dumps(body), "MISSING_FIELD")


def test_plain_http_transport_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["display"]["url"] = "http://example-words.trycloudflare.com/vnc.html"
    expect_code(json.dumps(body), "INSECURE_TRANSPORT")


def test_url_with_userinfo_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["display"]["url"] = "https://user:hunter2@host.trycloudflare.com/vnc.html"
    error = expect_code(json.dumps(body), "CREDENTIAL_IN_URL")
    assert "hunter2" not in str(error)


@pytest.mark.parametrize("query", ["token=abc123", "password=hunter2", "auth=zzz"])
def test_url_with_credential_query_is_rejected(query: str) -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["display"]["url"] = f"https://host.trycloudflare.com/vnc.html?{query}"
    error = expect_code(json.dumps(body), "CREDENTIAL_IN_URL")
    assert "hunter2" not in str(error)
    assert "abc123" not in str(error)


def test_url_with_credential_fragment_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["display"]["url"] = (
        "https://host.trycloudflare.com/vnc.html#password=hunter2"
    )
    error = expect_code(json.dumps(body), "CREDENTIAL_IN_URL")
    assert "hunter2" not in str(error)


def test_malformed_url_is_rejected_without_leaking() -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["display"]["url"] = "https://[::1/vnc.html"

    error = expect_code(json.dumps(body), "INVALID_FIELD")
    assert "::1" not in str(error)


def test_expired_descriptor_is_rejected() -> None:
    past = (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    expect_code(descriptor(expires_at=past), "AUTH_EXPIRED", now=NOW)


def test_expired_descriptor_can_be_inspected_when_expiry_check_is_off() -> None:
    past = (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    parsed = parse_descriptor(descriptor(expires_at=past), now=NOW, check_expiry=False)
    assert parsed.expires_at.endswith("Z")


def test_unparseable_expiry_is_rejected() -> None:
    expect_code(descriptor(expires_at="tomorrow"), "INVALID_TIMESTAMP", now=NOW)


def test_bad_geometry_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["display"]["geometry"] = [1280]
    expect_code(json.dumps(body), "INVALID_FIELD")


def test_unknown_guest_state_is_rejected() -> None:
    raw = descriptor()
    body = json.loads(raw)
    body["guest"]["state"] = "running"
    expect_code(json.dumps(body), "INVALID_FIELD")


def test_summary_never_contains_the_url() -> None:
    parsed = parse_descriptor(descriptor(), now=NOW)
    assert "trycloudflare" not in parsed.summary()


# ---- connect.py tests ----

def test_connect_error_not_ready_code() -> None:
    from tek_controller.connect import ConnectError
    exc = ConnectError("NOT_READY", "Session is initializing.")
    assert exc.code == "NOT_READY"
    assert "initializing" in exc.message


def test_connect_error_timeout_code() -> None:
    from tek_controller.connect import ConnectError
    exc = ConnectError("TIMEOUT", "No response within 20 s.")
    assert exc.code == "TIMEOUT"
