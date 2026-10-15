"""
Genesis OS — Level 3.3
Execution Maturity Contract

Updated for Level 3.5 Execution Safety integration.

Contract:

    malformed plan        -> invalid_plan
    missing target        -> missing_target
    unsafe operation      -> safety_blocked
    unknown operation     -> safety_blocked
    supported operation   -> execution
    execution failure     -> execution_failed
    unverified execution  -> verification_failed
"""

from unittest.mock import Mock

import pytest

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult


# =========================================================
# HELPERS
# =========================================================


def make_executor():
    return ActionExecutor(Mock())


def make_plan(
    operation="application.open",
    target="chrome",
    application="chrome",
    task="open chrome",
    confidence=0.97,
):
    return ActionPlan(
        operation=operation,
        target=target,
        application=application,
        task=task,
        confidence=confidence,
    )


# =========================================================
# ACTION PLAN FROM DECISION
# =========================================================


def test_action_plan_from_decision():

    decision = {
        "level": 3,
        "operation": "application.open",
        "target": "chrome",
        "application": "chrome",
        "confidence": 0.97,
        "parameters": {
            "operation": "open",
        },
        "reason": "Open application.",
    }

    plan = ActionPlan.from_decision(
        decision
    )

    assert plan.operation == "application.open"
    assert plan.target == "chrome"
    assert plan.application == "chrome"
    assert plan.confidence == 0.97
    assert plan.parameters["operation"] == "open"


# =========================================================
# SERIALIZATION
# =========================================================


def test_action_plan_serialization():

    plan = make_plan()

    data = plan.to_dict()

    assert isinstance(data, dict)
    assert data["operation"] == "application.open"
    assert data["target"] == "chrome"
    assert data["application"] == "chrome"
    assert data["confidence"] == 0.97


# =========================================================
# INVALID ACTION PLAN
# =========================================================


def test_invalid_action_plan_rejected():

    # Phase 1: ActionPlan is now a Pydantic BaseModel, so
    # ``operation=None`` is rejected at construction time
    # with a clear validation error instead of silently
    # reaching the executor. Same semantic contract
    # ("malformed plan is rejected") — earlier boundary.

    with pytest.raises(Exception) as exc_info:
        ActionPlan(
            operation=None,
            target="chrome",
            confidence=0.97,
        )

    message = str(exc_info.value)
    assert "operation" in message.lower()


# =========================================================
# MISSING TARGET
# =========================================================


def test_missing_target_rejected():

    # Phase 1: ``target=None`` for a non-targetless operation
    # is rejected at construction time by the Pydantic
    # ``_conditional_target_requirement`` model validator.
    # Same semantic contract ("missing target is rejected")
    # — earlier boundary, before the executor runs.

    with pytest.raises(Exception) as exc_info:
        ActionPlan(
            operation="application.open",
            target=None,
        )

    message = str(exc_info.value).lower()
    assert "target" in message


@pytest.mark.parametrize(
    ("operation", "method_name", "provider_result", "parameters"),
    [
        (
            "system.status",
            "system_status",
            {"success": True, "platform": "Windows", "verified": True},
            {},
        ),
        (
            "hardware.battery",
            "battery_status",
            {"success": True, "battery_present": False, "verified": True},
            {},
        ),
        (
            "hardware.stats",
            "hardware_stats",
            {"success": True, "cpu_percent": 12.5, "verified": True},
            {},
        ),
        (
            "clipboard.copy",
            "clipboard_copy",
            {"success": True, "content_match": True, "verified": True},
            {"text": "probe"},
        ),
    ],
)
def test_targetless_query_operations_dispatch(
    operation, method_name, provider_result, parameters
):
    os_manager = Mock()
    getattr(os_manager, method_name).return_value = provider_result
    executor = ActionExecutor(os_manager)
    plan = ActionPlan(
        operation=operation,
        target=None,
        parameters=parameters,
    )

    result = executor.execute(plan)

    assert result.success is True
    assert result.verified is True
    assert result.status == "verified"
    getattr(os_manager, method_name).assert_called_once()


def test_spreadsheet_sort_uses_explicit_source_output(workspace_root, monkeypatch):
    # The point of this test is that the arguments reach sheet_sort
    # UNCHANGED, so the literal relative strings in the assertions below
    # must stay literal. `source` and `output` are both scanned path
    # keys, and relative names resolve against cwd -- so making cwd the
    # workspace root keeps these names inside the boundary without
    # altering a single asserted value.
    monkeypatch.chdir(workspace_root)
    os_manager = Mock()
    os_manager.sheet_sort.return_value = {
        "success": True,
        "operation": "spreadsheet.sort",
        "executed": True,
        "verified": True,
        "output_matches": True,
    }
    executor = ActionExecutor(os_manager)
    plan = ActionPlan(
        operation="spreadsheet.sort",
        target="destination.xlsx",
        parameters={
            "source": "source.xlsx",
            "column": "Score",
            "output": "destination.xlsx",
            "confirmed": True,
        },
    )

    executor.execute(plan)

    os_manager.sheet_sort.assert_called_once_with(
        "source.xlsx",
        "Score",
        descending=True,
        output="destination.xlsx",
    )


# =========================================================
# UNSUPPORTED / DENIED OPERATION
# =========================================================


def test_unsupported_operation_rejected():

    executor = make_executor()

    plan = ActionPlan(
        operation="system.shutdown",
        target="computer",
        confidence=0.99,
    )

    result = executor.execute(plan)

    assert result.success is False
    assert result.status == "safety_blocked"
    assert result.executed is False
    assert result.verified is False
    assert result.error is not None

    assert (
        result.metadata["safety_status"]
        == "denied"
    )


# =========================================================
# OPEN APPLICATION
# =========================================================


def test_open_application_dispatch():

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

    plan = make_plan()

    result = executor.execute(
        plan
    )

    assert result.success is True
    assert result.status == "verified"
    assert result.executed is True
    assert result.verified is True

    os_manager.open_application.assert_called_once_with(
        "chrome"
    )


# =========================================================
# ALREADY RUNNING
# =========================================================


def test_already_running_is_success():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome is already running.",
        "already_running": True,
        "verified": True,
        "running": True,
        "executed": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.success is True
    assert result.status == "already_running"
    assert result.verified is True
    assert result.already_in_desired_state is True

    os_manager.open_application.assert_called_once()


# =========================================================
# ALREADY CLOSED
# =========================================================


def test_already_closed_is_success():

    os_manager = Mock()

    os_manager.close_application.return_value = {
        "success": True,
        "operation": "application.close",
        "application": "chrome",
        "message": "Chrome is already closed.",
        "already_closed": True,
        "verified": True,
        "running": False,
        "executed": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    plan = make_plan(
        operation="application.close",
        task="close chrome",
    )

    result = executor.execute(
        plan
    )

    assert result.success is True
    assert result.status == "already_closed"
    assert result.verified is True
    assert result.already_in_desired_state is True


# =========================================================
# EXECUTION FAILURE
# =========================================================


def test_execution_failure_is_reported():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": False,
        "operation": "application.open",
        "application": "chrome",
        "message": "Failed to open Chrome.",
        "error": "Application launch failed.",
        "executed": True,
        "verified": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.success is False
    assert result.status == "execution_failed"
    assert result.executed is True
    assert result.verified is False
    assert result.error is not None


# =========================================================
# VERIFICATION FAILURE
# =========================================================


def test_verification_failure_is_not_success():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome launch attempted.",
        "executed": True,
        "verified": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.success is True
    assert result.status == "verification_failed"
    assert result.executed is True
    assert result.verified is False


# =========================================================
# RESULT SERIALIZATION
# =========================================================


def test_result_serialization():

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
        make_plan()
    )

    data = result.to_dict()

    assert isinstance(data, dict)
    assert data["success"] is True
    assert data["operation"] == "application.open"
    assert data["target"] == "chrome"
    assert data["status"] == "verified"


# =========================================================
# RESULT EXPLANATION
# =========================================================


def test_result_explanation():

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
        make_plan()
    )

    explanation = result.explain()

    assert isinstance(
        explanation,
        str,
    )

    assert "execution" in explanation.lower()
    assert "verification" in explanation.lower()


# =========================================================
# LOW CONFIDENCE
# =========================================================


def test_low_confidence_plan_is_rejected():

    executor = make_executor()

    plan = make_plan(
        confidence=0.89
    )

    result = executor.execute(
        plan
    )

    assert result.success is False
    assert result.status == "invalid_plan"
    assert result.executed is False
    assert result.error is not None


# =========================================================
# CONFIDENCE BOUNDARY
# =========================================================


def test_confidence_boundary_is_accepted():

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

    plan = make_plan(
        confidence=0.90
    )

    result = executor.execute(
        plan
    )

    assert result.success is True
    assert result.status == "verified"


# =========================================================
# INVALID OPERATION NEVER EXECUTES
# =========================================================


def test_invalid_operation_is_rejected_before_execution():

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
    assert result.status == "safety_blocked"
    assert result.executed is False
    assert result.error is not None

    assert (
        result.metadata["safety_status"]
        == "denied"
    )

    assert os_manager.method_calls == []


# =========================================================
# EMPTY TARGET
# =========================================================


def test_empty_target_is_rejected():

    # Phase 1: empty target strings are rejected at
    # construction time by the Pydantic ``target`` field
    # validator. Same semantic contract — earlier boundary.

    with pytest.raises(Exception) as exc_info:
        make_plan(target="")

    message = str(exc_info.value).lower()
    assert "target" in message


# =========================================================
# NON-STRING TARGET
# =========================================================


def test_non_string_target_is_rejected():

    # Phase 1: non-string target values are rejected at
    # construction time by the Pydantic ``target`` field
    # validator. Same semantic contract — earlier boundary.

    with pytest.raises(Exception) as exc_info:
        make_plan(target=123)

    message = str(exc_info.value).lower()
    assert "target" in message


# =========================================================
# NON-FINITE CONFIDENCE
# =========================================================


@pytest.mark.parametrize(
    "confidence",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_confidence_is_rejected(
    confidence,
):

    # Phase 1: non-finite confidence values (nan, inf, -inf)
    # are rejected at construction time by the Pydantic
    # ``confidence`` field validator. Same semantic contract
    # — earlier boundary, before the executor runs.

    with pytest.raises(Exception) as exc_info:
        make_plan(
            confidence=confidence
        )

    message = str(exc_info.value).lower()
    assert "confidence" in message


# =========================================================
# EXECUTION EVIDENCE
# =========================================================


def test_execution_evidence_is_preserved():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome opened.",
        "executed": True,
        "verified": True,
        "running": True,
        "resolved_executable": "chrome.exe",
        "return_code": 0,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.execution["executed"] is True

    assert (
        result.execution[
            "resolved_executable"
        ]
        == "chrome.exe"
    )

    assert (
        result.execution["return_code"]
        == 0
    )


# =========================================================
# EXECUTED BUT UNVERIFIED
# =========================================================


def test_executed_but_unverified_is_not_trusted_success():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome launch attempted.",
        "executed": True,
        "verified": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.success is True
    assert result.executed is True
    assert result.verified is False
    assert result.status == "verification_failed"

    assert (
        result.metadata[
            "trustworthy_success"
        ]
        is False
    )


# =========================================================
# ALREADY RUNNING TRUST
# =========================================================


def test_already_running_is_trustworthy_desired_state():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome already running.",
        "already_running": True,
        "executed": False,
        "verified": True,
        "running": True,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.success is True
    assert result.status == "already_running"
    assert result.verified is True
    assert result.already_in_desired_state is True

    assert (
        result.metadata[
            "trustworthy_success"
        ]
        is True
    )


# =========================================================
# ALREADY CLOSED TRUST
# =========================================================


def test_already_closed_is_trustworthy_desired_state():

    os_manager = Mock()

    os_manager.close_application.return_value = {
        "success": True,
        "operation": "application.close",
        "application": "chrome",
        "message": "Chrome already closed.",
        "already_closed": True,
        "executed": False,
        "verified": True,
        "running": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    plan = make_plan(
        operation="application.close",
        task="close chrome",
    )

    result = executor.execute(
        plan
    )

    assert result.success is True
    assert result.status == "already_closed"
    assert result.verified is True
    assert result.already_in_desired_state is True

    assert (
        result.metadata[
            "trustworthy_success"
        ]
        is True
    )


def test_bare_verified_result_is_downgraded_after_dispatch():
    os_manager = Mock()
    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "executed": True,
        "verified": True,
        "message": "Provider self-reported success.",
    }
    executor = ActionExecutor(os_manager)

    result = executor.execute(make_plan())

    assert result.success is True
    assert result.executed is True
    assert result.verified is False
    assert result.status == "verification_unavailable"
    assert result.trustworthy_success is False
    assert "verification_evidence_rejected" in result.metadata
    os_manager.open_application.assert_called_once_with("chrome")


def test_error_forces_contradictory_success_to_fail():
    os_manager = Mock()
    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "executed": True,
        "verified": True,
        "running": True,
        "error": "provider contradicted itself",
        "verification": {"running": True},
    }
    executor = ActionExecutor(os_manager)

    result = executor.execute(make_plan())

    assert result.success is False
    assert result.verified is False
    assert result.status == "execution_failed"
    assert result.trustworthy_success is False
    assert "successfully" not in result.user_message().lower()
    assert "failed" in result.explain().lower()




# =========================================================
# PLAN PRESERVATION
# =========================================================


def test_plan_is_preserved_inside_result():

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

    plan = make_plan()

    result = executor.execute(
        plan
    )

    assert result.plan == plan.to_dict()


# =========================================================
# FINAL STATE
# =========================================================


def test_action_result_exposes_final_state():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "application": "chrome",
        "message": "Chrome opened.",
        "executed": True,
        "verified": True,
        "running": True,
        "running": True,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert result.success is True
    assert result.executed is True
    assert result.verified is True

    assert (
        result.verification["running"]
        is True
    )


# =========================================================
# USER MESSAGE SAFETY
# =========================================================


def test_action_result_user_message_is_safe():

    os_manager = Mock()

    os_manager.open_application.return_value = {
        "success": False,
        "operation": "application.open",
        "application": "chrome",
        "message": "Could not open Chrome.",
        "error": "Internal diagnostic detail.",
        "executed": True,
        "verified": False,
    }

    executor = ActionExecutor(
        os_manager
    )

    result = executor.execute(
        make_plan()
    )

    assert isinstance(
        result.message,
        str,
    )

    assert result.message != ""


# =========================================================
# EXPLANATION
# =========================================================


def test_explanation_contains_execution_and_verification():

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
        make_plan()
    )

    explanation = result.explain()

    text = explanation.lower()

    assert "execution" in text
    assert "verification" in text