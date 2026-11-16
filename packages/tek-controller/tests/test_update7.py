"""Update 7 tests — metrics, control panel, VNC/terminal windows."""
import sys, json, threading, urllib.request, urllib.error, pytest
# Skip tkinter-dependent tests if tkinter not installed
try:
    import tkinter as _tk
    _HAS_TK = True
except ModuleNotFoundError:
    _HAS_TK = False
tk_required = pytest.mark.skipif(not _HAS_TK, reason="tkinter not installed")
sys.path.insert(0,str(__import__("pathlib").Path(__file__).parent.parent))
sys.path.insert(0,str(__import__("pathlib").Path(__file__).parent.parent.parent / "tek-runtime"))

@tk_required
def test_control_panel_import():
    from tek_controller.views.control_panel import ControlPanelView
    assert ControlPanelView is not None

@tk_required
def test_vnc_window_import():
    from tek_controller.views.vnc_window import VncWindow
    assert VncWindow is not None

@tk_required
def test_terminal_window_import():
    from tek_controller.views.terminal_window import TerminalWindow,_WS_AVAILABLE
    assert TerminalWindow is not None; assert isinstance(_WS_AVAILABLE,bool)

@tk_required
def test_ws_available():
    from tek_controller.views.terminal_window import _WS_AVAILABLE
    if not _WS_AVAILABLE: pytest.skip("websocket-client not installed")

def test_fetch_metrics_import():
    from tek_controller.connect import fetch_metrics
    assert callable(fetch_metrics)

def test_fetch_metrics_bad_host():
    from tek_controller.connect import fetch_metrics,ConnectError
    from tek_controller.crypto import generate_secret
    with pytest.raises(ConnectError) as e:
        fetch_metrics(generate_secret(),"invalid.host.local","cookie",timeout_s=3)
    assert e.value.code in("TUNNEL_FAILED","TIMEOUT","HTTP_ERROR")

def test_no_secret_in_error():
    from tek_controller.connect import fetch_metrics,ConnectError
    from tek_controller.crypto import generate_secret
    import base64
    s=generate_secret(); s64=base64.urlsafe_b64encode(s).decode()
    try: fetch_metrics(s,"invalid","c",timeout_s=2)
    except ConnectError as exc:
        assert s64 not in exc.message; assert s.hex() not in exc.message

def test_health_returns_503_when_not_ready():
    """INTEGRATION: /tek/health returns 503 for not-ready proxy."""
    import http.server,socketserver
    from tek_runtime.authproxy import AuthProxy,_Handler
    class S(socketserver.ThreadingMixIn,http.server.HTTPServer):
        daemon_threads=True
        def finish_request(self,req,addr):
            h=self.RequestHandlerClass(req,addr,self); h.proxy=self._proxy
    p=AuthProxy(secret=b"\x00"*32); srv=S(("127.0.0.1",0),_Handler)
    srv._proxy=p; threading.Thread(target=srv.serve_forever,daemon=True).start()
    port=srv.server_address[1]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/tek/health",timeout=5)
        pytest.fail("Expected 503")
    except urllib.error.HTTPError as exc:
        assert exc.code==503
        d=json.loads(exc.read()); assert d["session_ready"] is False
    finally: srv.shutdown()

def test_metrics_returns_503_when_not_ready():
    """INTEGRATION: /tek/metrics returns 503 for not-ready proxy."""
    import http.server,socketserver
    from tek_runtime.authproxy import AuthProxy,_Handler
    class S(socketserver.ThreadingMixIn,http.server.HTTPServer):
        daemon_threads=True
        def finish_request(self,req,addr):
            h=self.RequestHandlerClass(req,addr,self); h.proxy=self._proxy
    p=AuthProxy(secret=b"\x00"*32); srv=S(("127.0.0.1",0),_Handler)
    srv._proxy=p; threading.Thread(target=srv.serve_forever,daemon=True).start()
    port=srv.server_address[1]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/tek/metrics",timeout=5)
        pytest.fail("Expected 503 or 401")
    except urllib.error.HTTPError as exc:
        assert exc.code in(503,401)
    finally: srv.shutdown()
