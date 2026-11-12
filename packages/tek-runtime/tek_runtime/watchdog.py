"""Process Watchdog — monitors QEMU, display bridge, auth proxy, and tunnel.

Design principles:
  - Each service has an explicit RestartPolicy (always / on-failure / never).
  - QEMU is NEVER auto-restarted — a restart would kill the guest OS and risk
    data loss. The watchdog notifies the session instead.
  - Restart attempts use exponential backoff (2 s → 4 s → 8 s … up to 60 s).
  - After max_restarts consecutive failures, the service is marked DEAD and the
    session is asked to shut down gracefully.
  - The watchdog runs in its own daemon thread; stopping it is cooperative.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable


class RestartPolicy(Enum):
    NEVER       = auto()   # never restart (QEMU)
    ON_FAILURE  = auto()   # restart only on unexpected exit
    ALWAYS      = auto()   # restart even on clean exit (tunnel, display)


class ServiceState(Enum):
    RUNNING  = auto()
    RESTARTING = auto()
    DEAD     = auto()
    STOPPED  = auto()


@dataclass
class ServiceConfig:
    name:           str
    is_alive:       Callable[[], bool]        # returns True if service is up
    start_fn:       Callable[[], None]        # how to restart the service
    policy:         RestartPolicy = RestartPolicy.ON_FAILURE
    max_restarts:   int           = 5
    base_backoff_s: float         = 2.0
    max_backoff_s:  float         = 60.0


@dataclass
class ServiceStatus:
    name:        str
    state:       ServiceState    = ServiceState.RUNNING
    restarts:    int             = 0
    last_error:  str             = ""
    last_seen:   float           = field(default_factory=time.time)


class ProcessWatchdog:
    """Monitors registered services and restarts them according to their policy."""

    def __init__(
        self,
        check_interval_s: float = 10.0,
        on_dead: Callable[[str], None] | None = None,
    ) -> None:
        self._interval = check_interval_s
        self._on_dead  = on_dead or (lambda name: None)
        self._services: dict[str, ServiceConfig]  = {}
        self._status:   dict[str, ServiceStatus]  = {}
        self._stop      = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #

    def register(self, cfg: ServiceConfig) -> None:
        self._services[cfg.name] = cfg
        self._status[cfg.name]   = ServiceStatus(name=cfg.name)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="TEK-Watchdog"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def statuses(self) -> list[ServiceStatus]:
        return list(self._status.values())

    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            for name, cfg in list(self._services.items()):
                self._check(name, cfg)

    def _check(self, name: str, cfg: ServiceConfig) -> None:
        status = self._status[name]
        if status.state in (ServiceState.DEAD, ServiceState.STOPPED,
                            ServiceState.RESTARTING):
            return

        try:
            alive = cfg.is_alive()
        except Exception as exc:
            alive = False
            status.last_error = str(exc)

        if alive:
            status.last_seen = time.time()
            return

        # Service is down
        if cfg.policy is RestartPolicy.NEVER:
            status.state = ServiceState.DEAD
            status.last_error = f"{name} stopped; policy=NEVER; not restarting."
            print(f"[Watchdog] {name}: DEAD (restart policy = NEVER). "
                  "Session will shut down.")
            self._on_dead(name)
            return

        if status.restarts >= cfg.max_restarts:
            status.state = ServiceState.DEAD
            status.last_error = (
                f"{name} failed {status.restarts} times; giving up."
            )
            print(f"[Watchdog] {name}: DEAD after {status.restarts} restarts.")
            self._on_dead(name)
            return

        # Attempt restart
        backoff = min(
            cfg.base_backoff_s * (2 ** status.restarts),
            cfg.max_backoff_s,
        )
        status.state    = ServiceState.RESTARTING
        status.restarts += 1
        print(f"[Watchdog] {name}: down — restart #{status.restarts} "
              f"in {backoff:.0f} s …")
        time.sleep(backoff)

        try:
            cfg.start_fn()
            status.state     = ServiceState.RUNNING
            status.last_seen = time.time()
            print(f"[Watchdog] {name}: restarted OK.")
        except Exception as exc:
            status.state      = ServiceState.RESTARTING
            status.last_error = str(exc)
            print(f"[Watchdog] {name}: restart failed — {exc}")
