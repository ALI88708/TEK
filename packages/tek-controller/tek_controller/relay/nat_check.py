"""NAT and public IP detection.

Checks whether the user's machine can receive inbound TCP connections from
the internet (required for the User-Owned Relay to work).

Steps:
  1. Detect external/public IP from multiple services.
  2. Open a temporary TCP listener on the target port.
  3. Use an external probe service to test reachability.
  4. Classify the result: OPEN / NAT / CGNAT / UNKNOWN.

LIMITATIONS:
  - Some corporate firewalls block outbound probes.
  - IPv6 reachability is checked separately.
  - The check can be a false-negative if the probe service is unavailable.
"""
from __future__ import annotations

import socket
import threading
import urllib.request
from dataclasses import dataclass
from enum import Enum, auto


class NatType(Enum):
    OPEN        = auto()   # inbound connections work
    NAT         = auto()   # behind NAT; port forwarding may help
    CGNAT       = auto()   # carrier-grade NAT; port forwarding won't help
    FIREWALL    = auto()   # public IP but inbound blocked by firewall
    UNKNOWN     = auto()   # check inconclusive


@dataclass
class NatCheckResult:
    public_ip:   str      = ""
    nat_type:    NatType  = NatType.UNKNOWN
    reachable:   bool     = False
    ipv6:        str      = ""
    ipv6_reach:  bool     = False
    detail:      str      = ""

    def friendly(self) -> str:
        if self.nat_type == NatType.OPEN:
            return f"✓ Reachable from internet (IP: {self.public_ip})"
        if self.nat_type == NatType.NAT:
            return (
                f"⚠ Behind NAT (external IP: {self.public_ip}). "
                "Configure port forwarding on your router to allow inbound TCP."
            )
        if self.nat_type == NatType.CGNAT:
            return (
                "✗ Carrier-Grade NAT detected. Your ISP shares one IP with many "
                "customers — inbound connections are not possible without a VPS or "
                "asking your ISP for a public IP. Use Cloudflare Tunnel instead."
            )
        if self.nat_type == NatType.FIREWALL:
            return (
                f"⚠ Public IP {self.public_ip} but inbound port blocked. "
                "Check Windows Firewall and your router's firewall settings."
            )
        return f"? Could not determine NAT type ({self.detail})"


# Services used to detect external IP
_IP_SERVICES = [
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
]

# CGNAT ranges (RFC 6598)
_CGNAT_RANGE = ("100.64.", "100.65.", "100.66.", "100.67.", "100.68.",
                "100.69.", "100.70.", "100.71.", "100.72.", "100.73.",
                "100.74.", "100.75.", "100.76.", "100.77.", "100.78.",
                "100.79.", "100.80.", "100.81.", "100.82.", "100.83.",
                "100.84.", "100.85.", "100.86.", "100.87.", "100.88.",
                "100.89.", "100.90.", "100.91.", "100.92.", "100.93.",
                "100.94.", "100.95.", "100.96.", "100.97.", "100.98.",
                "100.99.", "100.100.", "100.101.", "100.102.", "100.103.",
                "100.104.", "100.105.", "100.106.", "100.107.", "100.108.",
                "100.109.", "100.110.", "100.111.", "100.112.", "100.113.",
                "100.114.", "100.115.", "100.116.", "100.117.", "100.118.",
                "100.119.", "100.120.", "100.121.", "100.122.", "100.123.",
                "100.124.", "100.125.", "100.126.", "100.127.")
_PRIVATE = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
            "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
            "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
            "192.168.", "127.", "169.254.")


def _get_public_ip(timeout: float = 5.0) -> str:
    for url in _IP_SERVICES:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return ""


def _is_cgnat(ip: str) -> bool:
    return any(ip.startswith(p) for p in _CGNAT_RANGE)


def _is_private(ip: str) -> bool:
    return any(ip.startswith(p) for p in _PRIVATE)


def _probe_port(port: int, probe_timeout: float = 8.0) -> bool:
    """Open a listener then use portchecker.co to probe from outside.

    Returns True if the external probe could reach us.
    This is a best-effort check; it may be blocked by some firewalls.
    """
    # Open a local TCP listener
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    received = threading.Event()
    try:
        srv.bind(("", port))
        srv.listen(1)
        srv.settimeout(probe_timeout)

        def _accept():
            try:
                conn, _ = srv.accept()
                conn.close()
                received.set()
            except Exception:
                pass

        t = threading.Thread(target=_accept, daemon=True)
        t.start()

        # Ask an external service to probe us
        try:
            urllib.request.urlopen(
                f"https://portchecker.co/check?port={port}",
                timeout=probe_timeout,
            )
        except Exception:
            pass

        return received.wait(probe_timeout)
    except OSError:
        return False
    finally:
        try:
            srv.close()
        except Exception:
            pass


def check_public_access(
    port: int = 7000,
    *,
    probe: bool = True,
    timeout: float = 10.0,
) -> NatCheckResult:
    """Check whether the user's machine is reachable from the internet.

    Parameters
    ----------
    port    The port to test (should match frps bind_port).
    probe   If True, use an external probe service to verify reachability.
    timeout Per-request network timeout.
    """
    result = NatCheckResult()

    # Step 1: get external IP
    result.public_ip = _get_public_ip(timeout)
    if not result.public_ip:
        result.nat_type = NatType.UNKNOWN
        result.detail   = "Could not determine external IP."
        return result

    # Step 2: classify IP
    if _is_cgnat(result.public_ip):
        result.nat_type = NatType.CGNAT
        result.detail   = "IP is in CGNAT range (RFC 6598)."
        return result

    if _is_private(result.public_ip):
        result.nat_type = NatType.CGNAT
        result.detail   = "IP is private — behind double NAT or CGNAT."
        return result

    # Step 3: check reachability
    if probe:
        result.reachable = _probe_port(port, probe_timeout=timeout)
        if result.reachable:
            result.nat_type = NatType.OPEN
        else:
            # Has public IP but probe failed — NAT or firewall
            result.nat_type = NatType.NAT
            result.detail   = (
                "External probe could not reach the port. "
                "Check port forwarding or Windows Firewall."
            )
    else:
        result.nat_type = NatType.UNKNOWN
        result.detail   = "Probe skipped (probe=False)."

    return result
