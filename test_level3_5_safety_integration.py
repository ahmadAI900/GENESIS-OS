"""
Genesis OS — Level 3.5
Safety-Integrated Execution Contract

Level 3.5 guarantees that every ActionPlan passes through
ExecutionSafety before reaching the operating-system layer.

Architecture:

    ActionPlan
        ↓
    ExecutionSafety
        ↓
    ActionExecutor
        ↓
    OSManager

Safety invariants:

    1. Supported operations may proceed.
    2. Denied operations never reach OSManager.
    3. Unknown operations never reach OSManager.
    4. Invalid operations never reach OSManager.
    5. Safety decisions are preserved in ActionResult.
    6. Safety-blocked actions are never executed.
    7. Safety-blocked actions are never verified.
"""

from unittest.mock import Mock

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan


# =========================================================
# SUPPORTED OPERATION
# =========================================================


def test_supported_operation_passes_safety_gate():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "executed": True,
        "verified": True,
        "message": "Chrome opened.",
    }

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="application.open",
        target="chrome",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is True

    os_manager.open_application.assert_called_once_with(
        "chrome"
    )


# =========================================================
# DENIED OPERATION
# =========================================================


def test_denied_operation_is_blocked_before_execution():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="system.shutdown",
        target="computer",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False
    assert result.executed is False
    assert result.verified is False

    assert result.status == "safety_blocked"

    os_manager.open_application.assert_not_called()
    os_manager.close_application.assert_not_called()
    os_manager.inspect_application.assert_not_called()


# =========================================================
# UNKNOWN OPERATION
# =========================================================


def test_unknown_operation_is_blocked_before_execution():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan.model_construct(
        operation="something.completely_unknown",
        target="test",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False
    assert result.executed is False
    assert result.verified is False

    assert result.status == "safety_blocked"

    os_manager.open_application.assert_not_called()
    os_manager.close_application.assert_not_called()
    os_manager.inspect_application.assert_not_called()


# =========================================================
# SHELL EXECUTION
# =========================================================


def test_shell_execution_is_blocked():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="shell.execute",
        target="whoami",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False
    assert result.executed is False
    assert result.verified is False
    assert result.status == "safety_blocked"

    os_manager.open_application.assert_not_called()
    os_manager.close_application.assert_not_called()
    os_manager.inspect_application.assert_not_called()


# =========================================================
# FILESYSTEM DELETE
# =========================================================


def test_filesystem_delete_is_blocked():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="filesystem.delete",
        target="important.txt",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False
    assert result.executed is False
    assert result.verified is False
    assert result.status == "safety_blocked"

    os_manager.open_application.assert_not_called()
    os_manager.close_application.assert_not_called()
    os_manager.inspect_application.assert_not_called()


# =========================================================
# PROCESS KILL
# =========================================================


def test_process_kill_is_blocked():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="process.kill",
        target="1234",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False
    assert result.executed is False
    assert result.verified is False
    assert result.status == "safety_blocked"

    os_manager.open_application.assert_not_called()
    os_manager.close_application.assert_not_called()
    os_manager.inspect_application.assert_not_called()


# =========================================================
# SAFETY EVIDENCE
# =========================================================


def test_safety_decision_is_preserved():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="system.shutdown",
        target="computer",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False

    safety_decision = result.metadata.get(
        "safety_decision"
    )

    assert isinstance(
        safety_decision,
        dict,
    )

    assert safety_decision["operation"] == (
        "system.shutdown"
    )

    assert safety_decision["allowed"] is False

    assert safety_decision["status"] == (
        "denied"
    )


# =========================================================
# SAFETY STATUS
# =========================================================


def test_denied_operation_contains_safety_status():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="system.restart",
        target="computer",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.status == "safety_blocked"

    assert result.metadata.get(
        "safety_status"
    ) == "denied"


# =========================================================
# SAFETY REASON
# =========================================================


def test_safety_reason_is_preserved():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="shell.execute",
        target="whoami",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False

    reason = result.metadata.get(
        "safety_reason"
    )

    assert isinstance(
        reason,
        str,
    )

    assert reason


# =========================================================
# SAFETY BLOCK IS NOT EXECUTION
# =========================================================


def test_safety_block_is_not_execution_failure():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="system.shutdown",
        target="computer",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.status == "safety_blocked"

    assert result.executed is False

    assert result.verified is False

    assert result.error is not None


# =========================================================
# NO OS CALLS WHATSOEVER
# =========================================================


def test_safety_block_cannot_reach_os_manager():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan(
        operation="system.shutdown",
        target="computer",
        confidence=1.0,
    )

    executor.execute(
        plan
    )

    assert os_manager.method_calls == []