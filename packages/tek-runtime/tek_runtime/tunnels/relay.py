"""User-Owned Relay tunnel backend (frpc)."""
from __future__ import annotations
import os
from .. import relay_client as _rc
from .base import TunnelBackend, TunnelResult


class RelayTunnel(TunnelBackend):
    """frp-based User-Owned Relay tunnel.

    Requires TEK_RELAY_HOST, TEK_RELAY_PORT, TEK_RELAY_TOKEN,
    TEK_RELAY_AUTHPROXY_PORT in the environment (set by RelayManager
    on the controller side).
    """

    def __init__(self) -> None:
        self._host = ""
        self._port = 16080

    def start(self) -> TunnelResult:
        host  = os.environ.get("TEK_RELAY_HOST", "")
        port  = int(os.environ.get("TEK_RELAY_PORT", "7000"))
        token = os.environ.get("TEK_RELAY_TOKEN", "")
        rport = int(os.environ.get("TEK_RELAY_AUTHPROXY_PORT", "16080"))

        if not host or not token:
            raise RuntimeError(
                "TEK_RELAY_HOST and TEK_RELAY_TOKEN must be set to use "
                "the User-Owned Relay. Run RelayManager on the controller "
                "and pass its frpc_env to the Kaggle notebook."
            )

        _rc.start(
            server_addr=host,
            server_port=port,
            relay_token=token,
            relay_authproxy_port=rport,
        )
        self._host = host
        self._port = rport
        return TunnelResult(
            public_url=f"http://127.0.0.1:{rport}",
            host="127.0.0.1",
            port=rport,
            is_relay=True,
        )

    def stop(self) -> None:
        _rc.stop()

    def is_alive(self) -> bool:
        return _rc.is_alive()
