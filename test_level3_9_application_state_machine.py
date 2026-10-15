"""
Genesis OS — Level 3.9 Application State Machine Tests.

Tests the formal state machine for application lifecycle management.
Verifies state transitions, evidence tracking, and invalid transition rejection.
"""

import pytest

from genesis_os.application_state_machine import (
    ApplicationStateMachine,
    ApplicationLifecycle,
    AppState,
    StateTransition,
)


# =========================================================
# STATE MACHINE: Basic Transitions
# =========================================================


class TestBasicTransitions:
    """Verify fundamental state transitions work correctly."""

    def test_initial_state_is_unknown(self):
        sm = ApplicationStateMachine("chrome")
        assert sm.state == AppState.UNKNOWN

    def test_unknown_to_installed(self):
        sm = ApplicationStateMachine("chrome")
        result = sm.transition(AppState.INSTALLED, "discovered via Start Menu")
        assert result is True
        assert sm.state == AppState.INSTALLED

    def test_installed_to_starting(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.INSTALLED, "init")
        result = sm.transition(AppState.STARTING, "launch initiated")
        assert result is True
        assert sm.state == AppState.STARTING

    def test_starting_to_running(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STARTING, "init")
        result = sm.transition(AppState.RUNNING, "process detected")
        assert result is True
        assert sm.state == AppState.RUNNING

    def test_running_to_ready(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "init")
        result = sm.transition(AppState.READY, "application responsive")
        assert result is True
        assert sm.state == AppState.READY

    def test_ready_to_focused(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.READY, "init")
        result = sm.transition(AppState.FOCUSED, "window focused")
        assert result is True
        assert sm.state == AppState.FOCUSED

    def test_focused_to_ready_on_focus_loss(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.FOCUSED, "init")
        result = sm.transition(AppState.READY, "focus lost to another window")
        assert result is True
        assert sm.state == AppState.READY

    def test_ready_to_stopping(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.READY, "init")
        result = sm.transition(AppState.STOPPING, "close initiated")
        assert result is True
        assert sm.state == AppState.STOPPING

    def test_stopping_to_stopped(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STOPPING, "init")
        result = sm.transition(AppState.STOPPED, "process terminated")
        assert result is True
        assert sm.state == AppState.STOPPED

    def test_stopped_to_installed(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STOPPED, "init")
        result = sm.transition(AppState.INSTALLED, "process confirmed gone")
        assert result is True
        assert sm.state == AppState.INSTALLED


# =========================================================
# STATE MACHINE: Invalid Transitions
# =========================================================


class TestInvalidTransitions:
    """Invalid transitions must be rejected."""

    def test_not_installed_to_running_rejected(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.NOT_INSTALLED, "init")
        result = sm.transition(AppState.RUNNING, "attempt")
        assert result is False
        assert sm.state == AppState.NOT_INSTALLED

    def test_not_installed_to_focused_rejected(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.NOT_INSTALLED, "init")
        result = sm.transition(AppState.FOCUSED, "attempt")
        assert result is False
        assert sm.state == AppState.NOT_INSTALLED

    def test_starting_to_focused_rejected(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STARTING, "init")
        result = sm.transition(AppState.FOCUSED, "attempt")
        assert result is False
        assert sm.state == AppState.STARTING

    def test_stopped_to_running_rejected(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STOPPED, "init")
        result = sm.transition(AppState.RUNNING, "attempt")
        assert result is False
        assert sm.state == AppState.STOPPED

    def test_same_state_returns_true(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "init")
        result = sm.transition(AppState.RUNNING, "same state")
        assert result is True
        assert sm.state == AppState.RUNNING


# =========================================================
# STATE MACHINE: Recovery Transitions
# =========================================================


class TestRecoveryTransitions:
    """Verify recovery paths work correctly."""

    def test_unresponsive_to_running(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.UNRESPONSIVE, "init")
        result = sm.transition(AppState.RUNNING, "recovered after timeout")
        assert result is True
        assert sm.state == AppState.RUNNING

    def test_unresponsive_to_stopping(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.UNRESPONSIVE, "init")
        result = sm.transition(AppState.STOPPING, "force close")
        assert result is True
        assert sm.state == AppState.STOPPING

    def test_stopping_to_running_on_close_failure(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STOPPING, "init")
        result = sm.transition(AppState.RUNNING, "close failed, still running")
        assert result is True
        assert sm.state == AppState.RUNNING

    def test_starting_to_not_installed_on_failure(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.STARTING, "init")
        result = sm.transition(AppState.NOT_INSTALLED, "executable not found")
        assert result is True
        assert sm.state == AppState.NOT_INSTALLED

    def test_unknown_can_reach_any_state(self):
        """UNKNOWN is a special state that can transition to any state."""
        for target in [
            AppState.NOT_INSTALLED, AppState.INSTALLED,
            AppState.STARTING, AppState.RUNNING,
            AppState.READY, AppState.FOCUSED,
            AppState.UNRESPONSIVE, AppState.STOPPING,
            AppState.STOPPED,
        ]:
            sm = ApplicationStateMachine("test")
            result = sm.transition(target, "test")
            assert result is True, f"UNKNOWN -> {target.value} should be valid"
            assert sm.state == target


# =========================================================
# STATE MACHINE: History and Evidence
# =========================================================


class TestHistoryAndEvidence:
    """Every transition must be recorded with evidence."""

    def test_history_recorded(self):
        sm = ApplicationStateMachine("chrome")
        sm.transition(AppState.INSTALLED, "found in Start Menu")
        sm.transition(AppState.STARTING, "launch initiated")
        sm.transition(AppState.RUNNING, "process detected")

        assert len(sm.history) == 3
        assert sm.history[0].from_state == AppState.UNKNOWN
        assert sm.history[0].to_state == AppState.INSTALLED
        assert sm.history[0].evidence == "found in Start Menu"

    def test_history_preserves_evidence(self):
        sm = ApplicationStateMachine("chrome")
        sm.transition(AppState.RUNNING, "tasklist shows chrome.exe PID 1234")

        assert sm.history[0].evidence == "tasklist shows chrome.exe PID 1234"

    def test_history_timestamps(self):
        sm = ApplicationStateMachine("chrome")
        sm.transition(AppState.INSTALLED, "evidence1")
        sm.transition(AppState.STARTING, "evidence2")

        assert sm.history[0].timestamp <= sm.history[1].timestamp

    def test_to_dict_includes_history(self):
        sm = ApplicationStateMachine("chrome")
        sm.transition(AppState.RUNNING, "evidence")
        data = sm.to_dict()

        assert data["application"] == "chrome"
        assert data["state"] == "running"
        assert len(data["history"]) == 1
        assert data["history"][0]["evidence"] == "evidence"

    def test_history_metadata(self):
        sm = ApplicationStateMachine("chrome")
        sm.transition(
            AppState.RUNNING,
            "process detected",
            metadata={"pid": 1234, "cpu": "2.5%"},
        )

        assert sm.history[0].metadata["pid"] == 1234
        assert sm.history[0].metadata["cpu"] == "2.5%"


# =========================================================
# STATE MACHINE: can_transition
# =========================================================


class TestCanTransition:
    """can_transition should preview validity without applying."""

    def test_can_transition_valid(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.INSTALLED, "init")
        assert sm.can_transition(AppState.STARTING) is True

    def test_can_transition_invalid(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.INSTALLED, "init")
        assert sm.can_transition(AppState.RUNNING) is False

    def test_can_transition_does_not_change_state(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.INSTALLED, "init")
        sm.can_transition(AppState.STARTING)
        assert sm.state == AppState.INSTALLED


# =========================================================
# STATE MACHINE: force_state and reset
# =========================================================


class TestForceAndReset:
    """force_state and reset should work correctly."""

    def test_force_state(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "manual override")
        assert sm.state == AppState.RUNNING

    def test_force_state_recorded_in_history(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "manual override")
        assert len(sm.history) == 1
        assert sm.history[0].metadata.get("forced") is True

    def test_reset(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "init")
        sm.reset()
        assert sm.state == AppState.UNKNOWN

    def test_reset_recorded_in_history(self):
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "init")
        sm.reset()
        assert len(sm.history) == 2
        assert sm.history[1].to_state == AppState.UNKNOWN


# =========================================================
# APPLICATION LIFECYCLE
# =========================================================


class TestApplicationLifecycle:
    """ApplicationLifecycle combines state machine with metadata."""

    def test_lifecycle_creation(self):
        lc = ApplicationLifecycle(
            name="chrome",
            state_machine=ApplicationStateMachine("chrome"),
            executable="chrome.exe",
        )
        assert lc.name == "chrome"
        assert lc.state == AppState.UNKNOWN

    def test_lifecycle_to_dict(self):
        lc = ApplicationLifecycle(
            name="chrome",
            state_machine=ApplicationStateMachine("chrome"),
            executable="chrome.exe",
            process_id=1234,
        )
        data = lc.to_dict()
        assert data["name"] == "chrome"
        assert data["executable"] == "chrome.exe"
        assert data["process_id"] == 1234
        assert data["state"] == "unknown"

    def test_lifecycle_state_reflects_machine(self):
        sm = ApplicationStateMachine("chrome")
        lc = ApplicationLifecycle(name="chrome", state_machine=sm)
        sm.force_state(AppState.RUNNING, "init")
        assert lc.state == AppState.RUNNING

    def test_lifecycle_serialization(self):
        sm = ApplicationStateMachine("chrome")
        sm.transition(AppState.INSTALLED, "discovered")
        sm.transition(AppState.STARTING, "launching")
        lc = ApplicationLifecycle(name="chrome", state_machine=sm)
        data = lc.to_dict()
        assert data["machine"]["transition_count"] == 2
        assert len(data["machine"]["history"]) == 2


# =========================================================
# FULL LIFECYCLE SCENARIOS
# =========================================================


class TestFullLifecycleScenarios:
    """End-to-end lifecycle scenarios."""

    def test_happy_path_launch_focus_close(self):
        """Complete lifecycle: install -> start -> ready -> focus -> close."""
        sm = ApplicationStateMachine("chrome")
        sm.transition(AppState.INSTALLED, "discovered via Start Menu")
        sm.transition(AppState.STARTING, "launch initiated via subprocess")
        sm.transition(AppState.RUNNING, "tasklist shows chrome.exe")
        sm.transition(AppState.READY, "window responsive")
        sm.transition(AppState.FOCUSED, "window brought to foreground")
        sm.transition(AppState.READY, "focus moved to another window")
        sm.transition(AppState.STOPPING, "close initiated via taskkill")
        sm.transition(AppState.STOPPED, "process no longer in tasklist")

        assert sm.state == AppState.STOPPED
        assert len(sm.history) == 8

    def test_already_running_reuse(self):
        """Application already running -> READY without re-launch."""
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "detected already running")
        sm.transition(AppState.READY, "confirmed responsive")
        assert sm.state == AppState.READY

    def test_failed_launch_recovery(self):
        """Launch fails -> NOT_INSTALLED -> try alternative."""
        sm = ApplicationStateMachine("nonexistent_app")
        sm.transition(AppState.INSTALLED, "claimed installed")
        sm.transition(AppState.STARTING, "launch attempted")
        sm.transition(AppState.NOT_INSTALLED, "executable not found in PATH")

        assert sm.state == AppState.NOT_INSTALLED

    def test_unresponsive_recovery(self):
        """Application becomes unresponsive -> recovers."""
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "was running")
        sm.transition(AppState.UNRESPONSIVE, "window not responding")
        sm.transition(AppState.RUNNING, "recovered after 5 seconds")
        sm.transition(AppState.READY, "responsive again")
        assert sm.state == AppState.READY

    def test_unresponsive_force_close(self):
        """Application becomes unresponsive -> force close."""
        sm = ApplicationStateMachine("chrome")
        sm.force_state(AppState.RUNNING, "was running")
        sm.transition(AppState.UNRESPONSIVE, "window not responding")
        sm.transition(AppState.STOPPING, "force close initiated")
        sm.transition(AppState.STOPPED, "process terminated")
        assert sm.state == AppState.STOPPED
