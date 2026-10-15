"""
Genesis OS — Level 3.6
Capability Registry Integration Contract
"""

from unittest.mock import Mock

from genesis_os.action_executor import (
    ActionExecutor,
)

from genesis_os.action_plan import (
    ActionPlan,
)

from genesis_os.execution_safety import (
    ExecutionSafety,
)


def make_open_plan():

    return ActionPlan(
        operation="application.open",
        target="chrome",
        application="chrome",
        confidence=0.99,
    )


def test_supported_capability_reaches_execution():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome opened.",
            "executed": True,
            "verified": True,
            "running": True,
        }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_open_plan()
    )

    assert result.success is True

    assert result.status == "verified"

    os_manager.open_application.assert_called_once_with(
        "chrome"
    )


def test_denied_capability_never_reaches_os():

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

    assert result.status == (
        "safety_blocked"
    )

    assert result.executed is False

    assert result.verified is False

    assert result.error is not None

    assert (
        result.metadata[
            "safety_status"
        ]
        == "denied"
    )

    assert (
        result.metadata[
            "safety_decision"
        ]["allowed"]
        is False
    )

    assert os_manager.method_calls == []


def test_unknown_capability_never_reaches_os():

    os_manager = Mock()

    executor = ActionExecutor(
        os_manager
    )

    plan = ActionPlan.model_construct(
        operation="something.unknown",
        target="computer",
        confidence=0.99,
    )

    result = executor.execute(
        plan
    )

    assert result.success is False

    assert result.status == (
        "safety_blocked"
    )

    assert result.executed is False

    assert result.error is not None

    assert (
        result.metadata[
            "safety_status"
        ]
        == "unknown"
    )

    assert os_manager.method_calls == []


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

    decision = result.metadata[
        "safety_decision"
    ]

    assert decision["operation"] == (
        "system.shutdown"
    )

    assert decision["allowed"] is False

    assert decision["status"] == (
        "denied"
    )

    assert isinstance(
        decision["reason"],
        str,
    )


def test_supported_operation_is_allowed_by_safety():

    decision = ExecutionSafety.check(
        "application.open"
    )

    assert decision.allowed is True

    assert decision.status == (
        "supported"
    )