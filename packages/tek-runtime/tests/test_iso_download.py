"""ISO download path against a REAL local HTTP server (curl does the download)."""
import functools, hashlib, http.server, os, shutil, sys, threading
import pytest
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from tek_runtime.iso_manager import IsoError, IsoSpec, prepare

pytestmark = pytest.mark.skipif(not shutil.which("curl"), reason="curl not installed")
DATA = (b"\x5a" * (3 * 1024 * 1024))


@pytest.fixture
def web(tmp_path):
    root = tmp_path / "www"; root.mkdir()
    (root / "ok.iso").write_bytes(DATA)
    (root / "tiny.iso").write_bytes(b"x" * 100)
    H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    H.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "cache"
    srv.shutdown(); srv.server_close()


def test_download_and_verify_sha256(web):
    base, cache = web; cache.mkdir()
    sha = hashlib.sha256(DATA).hexdigest()
    path = prepare(IsoSpec.from_url(f"{base}/ok.iso", sha256=sha), cache_dir=str(cache))
    assert open(path, "rb").read() == DATA


def test_second_call_reuses_the_cached_download(web):
    base, cache = web; cache.mkdir()
    p1 = prepare(IsoSpec.from_url(f"{base}/ok.iso"), cache_dir=str(cache))
    mtime = os.path.getmtime(p1)
    p2 = prepare(IsoSpec.from_url(f"{base}/ok.iso"), cache_dir=str(cache))
    assert p1 == p2 and os.path.getmtime(p2) == mtime


def test_wrong_sha256_fails_and_removes_the_bad_download(web):
    base, cache = web; cache.mkdir()
    with pytest.raises(IsoError) as e:
        prepare(IsoSpec.from_url(f"{base}/ok.iso", sha256="0" * 64), cache_dir=str(cache))
    assert e.value.code == "SHA256_MISMATCH"
    assert not (cache / "ok.iso").exists(), "a corrupt download must not stay in the cache"


def test_404_is_a_clear_error(web):
    base, cache = web; cache.mkdir()
    with pytest.raises(IsoError) as e:
        prepare(IsoSpec.from_url(f"{base}/missing.iso"), cache_dir=str(cache))
    assert e.value.code == "ISO_DOWNLOAD_FAILED"


def test_too_small_download_is_rejected_and_removed(web):
    base, cache = web; cache.mkdir()
    with pytest.raises(IsoError) as e:
        prepare(IsoSpec.from_url(f"{base}/tiny.iso"), cache_dir=str(cache))
    assert e.value.code == "ISO_TOO_SMALL" and not (cache / "tiny.iso").exists()


def test_local_user_file_is_never_deleted_on_sha_mismatch(tmp_path):
    f = tmp_path / "mine.iso"; f.write_bytes(DATA)
    with pytest.raises(IsoError):
        prepare(IsoSpec.from_path(str(f), sha256="1" * 64))
    assert f.exists(), "TEK must not delete a file the user supplied"
