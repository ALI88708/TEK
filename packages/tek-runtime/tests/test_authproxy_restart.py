"""Regression: AuthProxy.stop() must release its port (found by the local e2e test)."""
import socket, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from tek_runtime.authproxy import AuthProxy
from tek_runtime.crypto import generate_secret


def _busy(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_stop_releases_the_listening_port():
    p = AuthProxy(secret=generate_secret()); p.start(); time.sleep(0.2)
    assert _busy(6080)
    p.stop()
    assert not _busy(6080)


def test_start_stop_start_in_same_process():
    for _ in range(3):
        p = AuthProxy(secret=generate_secret()); p.start(); time.sleep(0.1)
        assert _busy(6080)
        p.stop()
        assert not _busy(6080)
