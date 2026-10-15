"""
Genesis OS — Level 3.4.1
Execution Safety Contract

Tests the safety boundary BEFORE OS execution.

The safety layer must distinguish:

    SUPPORTED
    DENIED
    UNKNOWN
    INVALID

No OS operation should be performed by these tests.
"""

import pytest

from genesis_os.execution_safety import (
    ExecutionSafety,
    SafetyDecision,
)


# =========================================================
# SUPPORTED OPERATIONS
# =========================================================


def test_supported_application_open_is_allowed():

    decision = ExecutionSafety.check(
        "application.open"
    )

    assert isinstance(
        decision,
        SafetyDecision,
    )

    assert decision.allowed is True
    assert decision.status == "supported"


def test_supported_application_close_is_allowed():

    decision = ExecutionSafety.check(
        "application.close"
    )

    assert decision.allowed is True
    assert decision.status == "supported"


def test_supported_application_inspect_is_allowed():

    decision = ExecutionSafety.check(
        "application.inspect"
    )

    assert decision.allowed is True
    assert decision.status == "supported"


# =========================================================
# DENIED / UNSAFE OPERATIONS
# =========================================================


def test_system_shutdown_is_denied():

    decision = ExecutionSafety.check(
        "system.shutdown"
    )

    assert decision.allowed is False
    assert decision.status == "denied"


def test_system_restart_is_denied():

    decision = ExecutionSafety.check(
        "system.restart"
    )

    assert decision.allowed is False
    assert decision.status == "denied"


def test_shell_execute_is_denied():

    decision = ExecutionSafety.check(
        "shell.execute"
    )

    assert decision.allowed is False
    assert decision.status == "denied"


def test_filesystem_delete_is_denied():

    decision = ExecutionSafety.check(
        "filesystem.delete"
    )

    assert decision.allowed is False
    assert decision.status == "denied"


def test_process_kill_is_denied():

    decision = ExecutionSafety.check(
        "process.kill"
    )

    assert decision.allowed is False
    assert decision.status == "denied"


# =========================================================
# UNKNOWN OPERATIONS
# =========================================================


def test_unknown_operation_is_not_allowed():

    decision = ExecutionSafety.check(
        "something.completely_unknown"
    )

    assert decision.allowed is False
    assert decision.status == "unknown"


# =========================================================
# INVALID OPERATIONS
# =========================================================


def test_empty_operation_is_rejected():

    decision = ExecutionSafety.check(
        ""
    )

    assert decision.allowed is False
    assert decision.status == "invalid"


def test_whitespace_operation_is_rejected():

    decision = ExecutionSafety.check(
        "   "
    )

    assert decision.allowed is False
    assert decision.status == "invalid"


def test_non_string_operation_is_rejected():

    decision = ExecutionSafety.check(
        123
    )

    assert decision.allowed is False
    assert decision.status == "invalid"


# =========================================================
# SERIALIZATION
# =========================================================


def test_safety_decision_is_serializable():

    decision = ExecutionSafety.check(
        "application.open"
    )

    data = decision.to_dict()

    assert isinstance(
        data,
        dict,
    )

    assert data["allowed"] is True
    assert data["status"] == "supported"
    assert data["operation"] == "application.open"


# =========================================================
# DETERMINISM
# =========================================================


def test_safety_decision_is_deterministic():

    first = ExecutionSafety.check(
        "application.open"
    )

    second = ExecutionSafety.check(
        "application.open"
    )

    assert first.to_dict() == second.to_dict()