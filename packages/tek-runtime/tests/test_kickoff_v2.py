import sys, time
import pytest
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from tek_runtime.authproxy import AuthProxy
from tek_runtime.crypto import generate_secret, kickoff_token_v2, verify_kickoff_v2

N = "abcdefgh12345678"

def test_valid_token_verifies():
    s = generate_secret(); ts = int(time.time())
    assert verify_kickoff_v2(s, ts, N, kickoff_token_v2(s, ts, N))

def test_wrong_secret_rejected():
    ts = int(time.time())
    assert not verify_kickoff_v2(generate_secret(), ts, N, kickoff_token_v2(generate_secret(), ts, N))

def test_expired_and_future_rejected():
    s = generate_secret(); now = 1_000_000
    assert not verify_kickoff_v2(s, now - 301, N, kickoff_token_v2(s, now - 301, N), now=now)
    assert not verify_kickoff_v2(s, now + 301, N, kickoff_token_v2(s, now + 301, N), now=now)
    assert verify_kickoff_v2(s, now - 299, N, kickoff_token_v2(s, now - 299, N), now=now)

def test_token_is_bound_to_ts_and_nonce():
    s = generate_secret(); ts = int(time.time()); tok = kickoff_token_v2(s, ts, N)
    assert not verify_kickoff_v2(s, ts + 1, N, tok)
    assert not verify_kickoff_v2(s, ts, N + "x", tok)

@pytest.mark.parametrize("bad", ["", "short", "has space 12345", "x" * 65, "../../etc/passwd"])
def test_malformed_nonce_rejected(bad):
    s = generate_secret(); ts = int(time.time())
    assert not verify_kickoff_v2(s, ts, bad, kickoff_token_v2(s, ts, bad))

def test_claim_is_atomic_single_use_and_prunes():
    p = AuthProxy(secret=generate_secret())
    assert p.claim_kickoff(1, "n1") is True
    assert p.claim_kickoff(1, "n1") is False
    assert p.claim_kickoff(1, "n2") is True
    p._used_kickoffs[(9, "old")] = time.time() - 10_000
    p.claim_kickoff(2, "n3")
    assert (9, "old") not in p._used_kickoffs

def test_controller_and_runtime_derive_identical_tokens():
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "tek-controller"))
    from tek_controller.crypto import kickoff_token_v2 as ctl
    s = generate_secret(); ts = int(time.time())
    assert ctl(s, ts, N) == kickoff_token_v2(s, ts, N)
