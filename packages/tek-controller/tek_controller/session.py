"""Controller-side session state machine.

These six states are the Controller's view. They map onto the runtime lifecycle in
``docs/architecture.md`` section 6:

    Idle       <- created, ended
    Preparing  <- preparing, booting
    Connecting <- ready (viewer attaching)
    Running    <- connected
    Stopping   <- exporting, shutting down
    Failed     <- lost, failed

Pure Python: no Tk imports, so the transitions are unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "Idle"
    PREPARING = "Preparing"
    CONNECTING = "Connecting"
    RUNNING = "Running"
    STOPPING = "Stopping"
    FAILED = "Failed"


class InvalidTransition(RuntimeError):
    def __init__(self, source: SessionState, target: SessionState) -> None:
        super().__init__(f"{source.value} cannot transition to {target.value}")
        self.source = source
        self.target = target


ALLOWED_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.IDLE: frozenset({SessionState.PREPARING, SessionState.FAILED}),
    SessionState.PREPARING: frozenset(
        {SessionState.CONNECTING, SessionState.IDLE, SessionState.FAILED}
    ),
    SessionState.CONNECTING: frozenset(
        {SessionState.RUNNING, SessionState.IDLE, SessionState.FAILED}
    ),
    SessionState.RUNNING: frozenset({SessionState.STOPPING, SessionState.FAILED}),
    SessionState.STOPPING: frozenset({SessionState.IDLE, SessionState.FAILED}),
    SessionState.FAILED: frozenset({SessionState.IDLE}),
}

STATE_ORDER: tuple[SessionState, ...] = (
    SessionState.IDLE,
    SessionState.PREPARING,
    SessionState.CONNECTING,
    SessionState.RUNNING,
    SessionState.STOPPING,
    SessionState.FAILED,
)

STATE_HINTS: dict[SessionState, str] = {
    SessionState.IDLE: "No session. Nothing is running and nothing is reserved.",
    SessionState.PREPARING: "Preparing the session. No runtime link is established yet.",
    SessionState.CONNECTING: "Descriptor accepted. Attaching the viewer.",
    SessionState.RUNNING: "A viewer is attached to the guest display.",
    SessionState.STOPPING: "Shutting down. The guest disk is being finalized.",
    SessionState.FAILED: "The session stopped without completing.",
}


@dataclass(frozen=True, slots=True)
class SessionEvent:
    at: datetime
    state: SessionState
    message: str


@dataclass
class SessionModel:
    state: SessionState = SessionState.IDLE
    session_id: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    events: list[SessionEvent] = field(default_factory=list)

    def transition(self, target: SessionState, message: str) -> None:
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(self.state, target)

        if target is not SessionState.FAILED:
            self.failure_code = None
            self.failure_reason = None

        self.state = target
        self._record(message)

    def fail(self, code: str, reason: str) -> None:
        self.failure_code = code
        self.failure_reason = reason
        self.state = SessionState.FAILED
        self._record(f"{code}: {reason}")

    def bind_session(self, session_id: str) -> None:
        self.session_id = session_id

    def clear_session(self) -> None:
        self.session_id = None
        self.failure_code = None
        self.failure_reason = None

    def _record(self, message: str) -> None:
        self.events.append(
            SessionEvent(
                at=datetime.now(UTC),
                state=self.state,
                message=message,
            )
        )
