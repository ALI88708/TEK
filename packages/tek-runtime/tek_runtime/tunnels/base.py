"""Abstract base class for tunnel backends."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TunnelResult:
    """Information about an established tunnel."""
    public_url:   str    # https://... or http://localhost:PORT
    host:         str    # hostname or 'localhost'
    port:         int    # 443 for HTTPS, relay port for local
    is_relay:     bool   # True = User-Owned Relay, False = Cloudflare


class TunnelBackend(ABC):
    """Interface that every tunnel backend must implement."""

    @abstractmethod
    def start(self) -> TunnelResult:
        """Start the tunnel and return connection info."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the tunnel and clean up."""

    @abstractmethod
    def is_alive(self) -> bool:
        """Return True if the tunnel is currently running."""
