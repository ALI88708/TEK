"""Session state machine tests."""

from __future__ import annotations

import pytest

from tek_controller.session import (
    InvalidTransition,
    SessionModel,
    SessionState,
)


def test_initial_state_is_idle() -> None:
    model = SessionModel()
    assert model.state is SessionState.IDLE
    assert model.events == []


def test_idle_to_preparing_is_allowed() -> None:
    model = SessionModel()
    model.transition(SessionState.PREPARING, "create requested")
    assert model.state is SessionState.PREPARING


def test_idle_to_running_is_rejected() -> None:
    model = SessionModel()
    with pytest.raises(InvalidTransition):
        model.transition(SessionState.RUNNING, "skip ahead")
    assert model.state is SessionState.IDLE


def test_preparing_can_abort_back_to_idle() -> None:
    model = SessionModel()
    model.transition(SessionState.PREPARING, "create requested")
    model.transition(SessionState.IDLE, "runtime not implemented")
    assert model.state is SessionState.IDLE


def test_full_happy_path_ordering() -> None:
    model = SessionModel()
    model.transition(SessionState.PREPARING, "create")
    model.transition(SessionState.CONNECTING, "descriptor loaded")
    model.transition(SessionState.RUNNING, "viewer attached")
    model.transition(SessionState.STOPPING, "stop requested")
    model.transition(SessionState.IDLE, "stopped")

    assert [event.state for event in model.events] == [
        SessionState.PREPARING,
        SessionState.CONNECTING,
        SessionState.RUNNING,
        SessionState.STOPPING,
        SessionState.IDLE,
    ]


def test_failure_records_reason_and_code() -> None:
    model = SessionModel()
    model.transition(SessionState.PREPARING, "create")
    model.fail("RUNTIME_UNAVAILABLE", "no runtime reachable")

    assert model.state is SessionState.FAILED
    assert model.failure_code == "RUNTIME_UNAVAILABLE"
    assert model.failure_reason == "no runtime reachable"


def test_failed_can_be_cleared() -> None:
    model = SessionModel()
    model.fail("RUNTIME_UNAVAILABLE", "boom")
    model.transition(SessionState.IDLE, "reset")

    assert model.state is SessionState.IDLE
    assert model.failure_code is None


def test_events_carry_monotonic_timestamps() -> None:
    model = SessionModel()
    model.transition(SessionState.PREPARING, "one")
    model.transition(SessionState.IDLE, "two")

    first, second = model.events
    assert second.at >= first.at
    assert first.message == "one"


def test_descriptor_binding_sets_session_id() -> None:
    model = SessionModel()
    model.bind_session("s_01J9Z6K3W7")
    assert model.session_id == "s_01J9Z6K3W7"
    model.clear_session()
    assert model.session_id is None


def test_state_labels_are_the_documented_ones() -> None:
    assert [state.value for state in SessionState] == [
        "Idle",
        "Preparing",
        "Connecting",
        "Running",
        "Stopping",
        "Failed",
    ]
