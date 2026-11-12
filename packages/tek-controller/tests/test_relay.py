"""Unit tests for relay components."""
from __future__ import annotations
import sys
import pytest
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

class TestNatCheck:
    def test_cgnat_ip_detected(self):
        from tek_controller.relay.nat_check import _is_cgnat
        assert _is_cgnat("100.64.0.1")  # RFC 6598
        assert not _is_cgnat("1.2.3.4")

    def test_private_ip_detected(self):
        from tek_controller.relay.nat_check import _is_private
        assert _is_private("192.168.1.1")
        assert _is_private("10.0.0.1")
        assert not _is_private("8.8.8.8")

    def test_nat_result_friendly_cgnat(self):
        from tek_controller.relay.nat_check import NatCheckResult, NatType
        r = NatCheckResult(public_ip="100.64.1.1", nat_type=NatType.CGNAT)
        assert "CGNAT" in r.friendly() or "ISP" in r.friendly()

    def test_nat_result_friendly_open(self):
        from tek_controller.relay.nat_check import NatCheckResult, NatType
        r = NatCheckResult(public_ip="1.2.3.4", nat_type=NatType.OPEN, reachable=True)
        assert "1.2.3.4" in r.friendly()


class TestRelayToken:
    def test_relay_token_matches_both_sides(self):
        """UNIT: controller and runtime derive the same relay token."""
        import sys, importlib
        sys.path.insert(0, "/tmp/TEK_v6/packages/tek-runtime")
        from tek_controller.crypto import generate_secret
        from tek_controller.crypto import relay_token as ct_relay
        # Force reload from local source, not installed wheel
        import tek_runtime.crypto as _rtcrypto
        importlib.reload(_rtcrypto)
        from tek_runtime.crypto import relay_token as rt_relay
        secret = generate_secret()
        assert ct_relay(secret) == rt_relay(secret)

    def test_relay_token_is_43_chars(self):
        from tek_controller.crypto import generate_secret, relay_token
        s = generate_secret()
        t = relay_token(s)
        assert len(t) == 43
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in t)


class TestFetchWithRetry:
    def test_retries_on_timeout(self):
        """UNIT: TIMEOUT errors are retried."""
        from tek_controller.connect import ConnectError, fetch_with_retry
        from tek_controller.crypto import generate_secret
        import unittest.mock as mock
        secret = generate_secret()
        calls = []
        def _fake(*a, **kw):
            calls.append(1)
            raise ConnectError("TIMEOUT", "No response.")
        with mock.patch("tek_controller.connect.fetch_descriptor", _fake):
            with pytest.raises(ConnectError) as exc_info:
                fetch_with_retry(secret, "example.com",
                                 max_attempts=3, base_backoff_s=0.01)
        assert len(calls) == 3

    def test_no_retry_on_auth_failed(self):
        """UNIT: AUTH_FAILED must NOT be retried."""
        from tek_controller.connect import ConnectError, fetch_with_retry
        from tek_controller.crypto import generate_secret
        import unittest.mock as mock
        secret = generate_secret()
        calls = []
        def _fake(*a, **kw):
            calls.append(1)
            raise ConnectError("AUTH_FAILED", "Bad token.")
        with mock.patch("tek_controller.connect.fetch_descriptor", _fake):
            with pytest.raises(ConnectError):
                fetch_with_retry(secret, "example.com", max_attempts=3)
        assert len(calls) == 1   # stopped immediately

    def test_on_attempt_callback_called(self):
        """UNIT: on_attempt callback receives attempt number."""
        from tek_controller.connect import ConnectError, fetch_with_retry
        from tek_controller.crypto import generate_secret
        import unittest.mock as mock
        secret = generate_secret()
        seen = []
        def _fake(*a, **kw): raise ConnectError("TIMEOUT", "x.")
        def _cb(attempt, msg): seen.append(attempt)
        with mock.patch("tek_controller.connect.fetch_descriptor", _fake):
            with pytest.raises(ConnectError):
                fetch_with_retry(secret, "h", max_attempts=2,
                                 base_backoff_s=0.01, on_attempt=_cb)
        # on_attempt fires at start of each attempt AND at retry message,
        # so attempt-1 appears twice: [1(start), 1(retry-msg), 2(start)]
        assert seen[0] == 1
        assert 2 in seen
