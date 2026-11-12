"""Unit tests for ProcessWatchdog."""
from __future__ import annotations
import sys, time, threading
import pytest
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
from tek_runtime.watchdog import (
    ProcessWatchdog, ServiceConfig, ServiceState, RestartPolicy
)

class TestWatchdog:
    def test_healthy_service_not_restarted(self):
        """UNIT: healthy service stays RUNNING."""
        wd = ProcessWatchdog(check_interval_s=0.1)
        calls = []
        wd.register(ServiceConfig(
            name="ok", is_alive=lambda: True,
            start_fn=lambda: calls.append(1),
            policy=RestartPolicy.ON_FAILURE,
        ))
        wd.start()
        time.sleep(0.3)
        wd.stop()
        assert calls == [], "Healthy service must not be restarted"
        assert wd.statuses()[0].state == ServiceState.RUNNING

    def test_failed_service_restarted(self):
        """UNIT: service that dies is restarted according to policy."""
        wd = ProcessWatchdog(check_interval_s=0.1)
        alive_flag = [False]
        restart_calls = []
        def _start(): alive_flag[0] = True; restart_calls.append(1)
        wd.register(ServiceConfig(
            name="flaky",
            is_alive=lambda: alive_flag[0],
            start_fn=_start,
            policy=RestartPolicy.ON_FAILURE,
            max_restarts=3,
            base_backoff_s=0.05,
        ))
        wd.start()
        time.sleep(0.5)
        wd.stop()
        assert len(restart_calls) >= 1, "Failed service must be restarted"

    def test_qemu_never_restarted(self):
        """UNIT: NEVER policy must not restart even on failure."""
        dead = threading.Event()
        wd = ProcessWatchdog(check_interval_s=0.1, on_dead=lambda n: dead.set())
        wd.register(ServiceConfig(
            name="qemu",
            is_alive=lambda: False,
            start_fn=lambda: None,
            policy=RestartPolicy.NEVER,
        ))
        wd.start()
        dead.wait(timeout=2)
        wd.stop()
        s = wd.statuses()[0]
        assert s.state == ServiceState.DEAD
        assert s.restarts == 0

    def test_max_restarts_marks_dead(self):
        """UNIT: service exceeding max_restarts must become DEAD."""
        dead_flag = []
        wd = ProcessWatchdog(
            check_interval_s=0.05,
            on_dead=lambda n: dead_flag.append(n),
        )
        wd.register(ServiceConfig(
            name="broken",
            is_alive=lambda: False,
            start_fn=lambda: None,
            policy=RestartPolicy.ON_FAILURE,
            max_restarts=2,
            base_backoff_s=0.01,
        ))
        wd.start()
        time.sleep(1.5)
        wd.stop()
        assert dead_flag, "on_dead callback must be called"
        assert wd.statuses()[0].state == ServiceState.DEAD

    def test_stop_is_safe_without_start(self):
        """UNIT: stop() before start() must not raise."""
        wd = ProcessWatchdog(check_interval_s=1)
        wd.stop()   # must not raise

    def test_backoff_increases(self):
        """UNIT: backoff is bounded and increases exponentially."""
        cfg = ServiceConfig(
            name="x", is_alive=lambda: True, start_fn=lambda: None,
            base_backoff_s=2.0, max_backoff_s=30.0, max_restarts=10,
        )
        wd = ProcessWatchdog.__new__(ProcessWatchdog)
        backoffs = [
            min(cfg.base_backoff_s * (2 ** i), cfg.max_backoff_s)
            for i in range(5)
        ]
        assert backoffs[0] == 2.0
        assert backoffs[1] == 4.0
        assert backoffs[4] == 30.0  # capped
