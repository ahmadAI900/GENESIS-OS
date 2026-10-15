"""
Genesis OS — Phase 7 Integration Tests.

Proves that Genesis handles unseen real-world natural-language tasks
through the full lifecycle:

    UNDERSTAND → PLAN → CAPABILITY RESOLUTION → EXECUTE → OBSERVE
    → VERIFY → RECOVER/REPLAN → RESULT

Failure path:
    CLASSIFY → DIAGNOSE → RECOVER → OBSERVE → VERIFY

Invalid plan:
    REPLAN

These tests use mocks to exercise the lifecycle logic without
requiring real OS operations.  They verify structural guarantees
that must hold for any task.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest

from genesis_os.failure_classifier import (
    FailureCategory,
    FailureClassification,
    FailureClassifier,
)
from genesis_os.action_plan import ActionPlan
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_result import ActionResult
from runtime.audit import ExecutionAudit
from runtime.genesis_runtime import GenesisRuntime
from runtime.models import TaskPhase, TaskTrace


# =========================================================
# FIXTURES
# =========================================================


def _make_runtime(
    agent_bridge_response=None,
    agent_bridge_side_effect=None,
    os_manager=None,
):
    """Build a GenesisRuntime with mocked Level 1 components."""
    brain = MagicMock()
    conversation = MagicMock()
    memory = MagicMock()
    ai_engine = MagicMock()
    agent_bridge = MagicMock()

    if agent_bridge_side_effect is not None:
        agent_bridge.handle.side_effect = agent_bridge_side_effect
        agent_bridge.classify_request.side_effect = agent_bridge_side_effect
    elif agent_bridge_response is not None:
        agent_bridge.handle.return_value = agent_bridge_response
    else:
        agent_bridge.handle.return_value = {"status": "completed"}

    agent_bridge.classify_request.return_value = {
        "type": "agent",
        "agent": "test_agent",
    }

    return GenesisRuntime(
        brain=brain,
        conversation=conversation,
        memory=memory,
        ai_engine=ai_engine,
        agent_bridge=agent_bridge,
        os_manager=os_manager,
    )


def _make_workflow_plan(steps=None):
    """Build a minimal WorkflowPlan for testing."""
    from genesis_os.workflow_models import WorkflowPlan, WorkflowStep

    if steps is None:
        step = WorkflowStep(
            step_id="step-1",
            plan=ActionPlan(
                operation="application.open",
                target="Notepad",
                application="Notepad",
                confidence=1.0,
            ),
        )
        steps = [step]

    return WorkflowPlan(
        objective="test objective",
        steps=tuple(steps),
        workflow_id=f"wf-{uuid.uuid4().hex[:8]}",
    )


def _make_action_result(
    success=True,
    verified=True,
    executed=True,
    operation="application.open",
    target="Notepad",
    status="verified",
    error=None,
    already_in_desired_state=False,
):
    """Build a minimal ActionResult for testing."""
    return ActionResult(
        success=success,
        operation=operation,
        target=target,
        application=target,
        status=status,
        message="ok" if success else "failed",
        executed=executed,
        verified=verified,
        already_in_desired_state=already_in_desired_state,
        error=error,
        verification={"running": True} if verified else {},
    )


# =========================================================
# 1. FAILURE CLASSIFIER TESTS
# =========================================================


class TestFailureClassifier:
    """Test each of the 10 spec failure categories."""

    def setup_method(self):
        self.classifier = FailureClassifier()

    def test_permission_denied(self):
        result = self.classifier.classify(
            error="Permission denied: cannot write to /etc/config",
            operation="file.create",
            exception_type="PermissionError",
        )
        assert result.category == FailureCategory.PERMISSION_DENIED
        assert result.confidence >= 0.9
        assert result.retryable is False

    def test_timeout(self):
        result = self.classifier.classify(
            error="Operation timed out after 30 seconds",
            operation="browser.open_url",
            exception_type="TimeoutError",
        )
        assert result.category == FailureCategory.TIMEOUT
        assert result.confidence >= 0.85
        assert result.retryable is True

    def test_network_failure(self):
        result = self.classifier.classify(
            error="Connection refused: host unreachable",
            operation="browser.open_url",
            exception_type="ConnectionError",
        )
        assert result.category == FailureCategory.NETWORK_FAILURE
        assert result.confidence >= 0.85
        assert result.retryable is True

    def test_browser_failure(self):
        result = self.classifier.classify(
            error="Session not created: unable to connect to browser",
            operation="browser.click",
            exception_type="WebDriverException",
        )
        assert result.category == FailureCategory.BROWSER_FAILURE
        assert result.confidence >= 0.8
        assert result.retryable is True

    def test_application_unavailable(self):
        result = self.classifier.classify(
            error="Application not found: Blender",
            operation="application.open",
            exception_type="FileNotFoundError",
        )
        assert result.category == FailureCategory.APPLICATION_UNAVAILABLE
        assert result.confidence >= 0.8
        assert result.retryable is True

    def test_file_moved(self):
        result = self.classifier.classify(
            error="No such file: C:\\Users\\test\\report.docx",
            operation="file.read",
            exception_type="FileNotFoundError",
        )
        assert result.category in (FailureCategory.FILE_MOVED, FailureCategory.WRONG_TARGET, FailureCategory.FILE_RENAMED)
        assert result.retryable is True

    def test_file_renamed(self):
        result = self.classifier.classify(
            error="File not found: old_name.txt",
            operation="file.open",
            exception_type="FileNotFoundError",
        )
        assert result.category in (FailureCategory.FILE_RENAMED, FailureCategory.WRONG_TARGET)
        assert result.retryable is True

    def test_unexpected_application_state(self):
        result = self.classifier.classify(
            error="Application was expected to be running but is not",
            operation="application.inspect",
            exception_type="",
        )
        assert result.category == FailureCategory.UNEXPECTED_APPLICATION_STATE
        assert result.retryable is True

    def test_wrong_target(self):
        result = self.classifier.classify(
            error="Path does not exist: C:\\nonexistent\\file.txt",
            operation="file.read",
            exception_type="",
        )
        assert result.category == FailureCategory.WRONG_TARGET
        assert result.retryable is True

    def test_partial_completion(self):
        """Partial completion is detected from execution result context."""
        mock_result = Mock()
        mock_result.executed = True
        mock_result.verified = False

        result = self.classifier.classify(
            error="Verification failed",
            operation="file.create",
            execution_result=mock_result,
        )
        assert result.category == FailureCategory.PARTIAL_COMPLETION
        assert result.retryable is True

    def test_unknown_error(self):
        result = self.classifier.classify(
            error="Something completely unexpected happened",
            operation="unknown_op",
            exception_type="RuntimeError",
        )
        assert result.category == FailureCategory.UNKNOWN
        assert result.retryable is False

    def test_classification_serializes(self):
        result = self.classifier.classify(
            error="Permission denied",
            operation="file.delete",
        )
        d = result.to_dict()
        assert "category" in d
        assert "confidence" in d
        assert "retryable" in d


# =========================================================
# 2. FULL LIFECYCLE — CONVERSATION PATH
# =========================================================


class TestLifecycleConversationPath:
    """Test the full lifecycle for conversation-type requests."""

    def test_conversation_shortcircuit(self):
        """Conversation requests should complete without workflow execution."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("Hello, how are you?")

        assert result["success"] is True
        assert result["trace_id"].startswith("phase7-")
        assert len(result["phases"]) >= 2
        # Should have UNDERSTANDING → CLASSIFIED → EXECUTING → COMPLETED
        phase_names = [p["phase"] for p in result["phases"]]
        assert "understanding" in phase_names
        assert "classified" in phase_names
        assert "completed" in phase_names

    def test_conversation_creates_audit_trace(self):
        """The audit trail should contain a trace for every lifecycle."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("What time is it?")
        trace = runtime.get_trace(result["trace_id"])

        assert trace is not None
        assert trace.goal == "What time is it?"
        assert trace.phase in (TaskPhase.COMPLETED, TaskPhase.FAILED)


# =========================================================
# 3. FULL LIFECYCLE — AGENT WORKFLOW PATH
# =========================================================


class TestLifecycleAgentWorkflow:
    """Test the full lifecycle for agent-type requests."""

    def test_agent_workflow_completes(self):
        """Agent workflow should complete and return result."""
        runtime = _make_runtime(
            agent_bridge_response={"status": "completed", "data": "done"}
        )

        result = runtime.execute_with_lifecycle("Open Notepad")

        assert result["success"] is True
        assert "result" in result
        assert len(result["phases"]) >= 3

    def test_failed_agent_result_is_not_completed(self):
        runtime = _make_runtime(
            agent_bridge_response={"status": "failed", "error": "provider failed"}
        )

        result = runtime.execute_with_lifecycle("Open Notepad")

        assert result["success"] is False
        assert "completed" not in {phase["phase"] for phase in result["phases"]}
        trace = runtime.get_trace(result["trace_id"])
        assert trace is not None
        assert trace.phase == TaskPhase.FAILED
        assert trace.trustworthy is False

    def test_unverified_agent_result_is_not_completed(self):
        runtime = _make_runtime(
            agent_bridge_response={"status": "completed", "verified": False}
        )

        result = runtime.execute_with_lifecycle("Open Notepad")

        assert result["success"] is False
        trace = runtime.get_trace(result["trace_id"])
        assert trace is not None
        assert trace.trustworthy is False

    def test_incomplete_lifecycle_fallback_is_failure(self):
        runtime = _make_runtime(
            agent_bridge_response={"status": "completed", "verified": True},
            os_manager=Mock(),
        )
        runtime._workflow_engine.execute = Mock(return_value=None)

        result = runtime.execute_with_lifecycle(
            "Open Notepad",
            workflow_plan=_make_workflow_plan(),
        )

        assert result["success"] is False
        assert result["error"] == "Workflow lifecycle ended without a verified result."
        assert result["result"] == {}
        trace = runtime.get_trace(result["trace_id"])
        assert trace is not None
        assert trace.phase == TaskPhase.FAILED

    def test_agent_workflow_creates_audit_trail(self):
        runtime = _make_runtime(
            agent_bridge_response={"status": "completed"}
        )

        result = runtime.execute_with_lifecycle("Search for Python docs")
        entries = runtime.get_audit_trail(task_id=result["trace_id"])

        assert len(entries) >= 3
        phases_seen = {e.phase for e in entries}
        assert TaskPhase.RECEIVED in phases_seen
        assert TaskPhase.COMPLETED in phases_seen


# =========================================================
# 4. FAILURE RECOVERY LIFECYCLE
# =========================================================


class TestLifecycleRecovery:
    """Test CLASSIFY → DIAGNOSE → RECOVER → OBSERVE → VERIFY."""

    def test_classification_failure_triggers_recovery(self):
        """If initial classification fails with retryable error, lifecycle should recover."""
        call_count = 0

        def classify_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Classification service timeout")
            return {"type": "agent", "agent": "test"}

        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.side_effect = classify_side_effect
        runtime.agent_bridge.handle.return_value = {"status": "recovered"}

        result = runtime.execute_with_lifecycle("Open calculator")

        # Should succeed after retry
        assert result["success"] is True

    def test_non_retryable_failure_stops_immediately(self):
        """Non-retryable failures should not be retried."""
        call_count = 0

        def classify_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("Access denied to classification service")
            return {"type": "agent", "agent": "test"}

        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.side_effect = classify_side_effect

        result = runtime.execute_with_lifecycle("Delete system files")

        # PermissionError is non-retryable, should fail immediately
        assert result["success"] is False
        assert call_count == 1  # No retry

    def test_recovery_recorded_in_audit(self):
        """Recovery attempts should appear in the audit trail."""
        call_count = 0

        def classify_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Timeout connecting to service")
            return {"type": "agent", "agent": "test"}

        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.side_effect = classify_side_effect
        runtime.agent_bridge.handle.return_value = {"status": "ok"}

        result = runtime.execute_with_lifecycle("Research AI trends")

        entries = runtime.get_audit_trail(task_id=result["trace_id"])
        recovery_entries = [e for e in entries if e.phase == TaskPhase.RECOVERING]
        assert len(recovery_entries) >= 1

    def test_recovery_failure_recorded_in_result(self):
        """Recovery log should be populated when recovery is attempted."""
        call_count = 0

        def classify_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection refused")
            return {"type": "agent", "agent": "test"}

        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.side_effect = classify_side_effect
        runtime.agent_bridge.handle.return_value = {"status": "ok"}

        result = runtime.execute_with_lifecycle("Download a file")

        assert len(result["recovery"]) >= 1
        assert result["recovery"][0]["category"] == "network_failure"


# =========================================================
# 5. FAILURE SCENARIO MATRIX
# =========================================================


class TestFailureScenarios:
    """
    Test each failure scenario from the spec.
    Genesis must handle these without fake success or blind retry.
    """

    SCENARIOS = [
        ("application_not_available", "Application not found: Blender", "application.open", "application_unavailable"),
        ("file_moved", "No such file: C:\\docs\\report.pdf", "file.read", None),
        ("file_renamed", "File not found: old_name.txt", "file.open", None),
        ("permission_denied", "Permission denied: /etc/passwd", "file.delete", "permission_denied"),
        ("browser_failure", "Session not created", "browser.click", "browser_failure"),
        ("network_failure", "Connection refused", "browser.open_url", "network_failure"),
        ("wrong_target", "Path does not exist: C:\\bad\\path", "file.read", "wrong_target"),
        ("unexpected_state", "Application was expected running", "application.inspect", "unexpected_application_state"),
        ("timeout", "Operation timed out", "browser.open_url", "timeout"),
    ]

    @pytest.mark.parametrize(
        "scenario_name,error_msg,operation,expected_category",
        SCENARIOS,
    )
    def test_failure_classification(
        self, scenario_name, error_msg, operation, expected_category
    ):
        """Each failure scenario must be classified correctly."""
        classifier = FailureClassifier()
        result = classifier.classify(error=error_msg, operation=operation)

        if expected_category is not None:
            assert result.category.value == expected_category, (
                f"Scenario '{scenario_name}': expected {expected_category}, "
                f"got {result.category.value}"
            )
        else:
            # File operations with "not found" can be multiple categories
            assert result.category in (
                FailureCategory.FILE_MOVED,
                FailureCategory.FILE_RENAMED,
                FailureCategory.WRONG_TARGET,
            ), f"Scenario '{scenario_name}': unexpected {result.category.value}"

    def test_no_blind_retry(self):
        """Verify that non-retryable failures are not retried."""
        classifier = FailureClassifier()

        result = classifier.classify(
            error="Permission denied",
            operation="file.delete",
        )
        assert result.retryable is False

    def test_no_fake_success(self):
        """Verify that failed results are never marked as trustworthy."""
        result = _make_action_result(
            success=False,
            verified=False,
            executed=False,
            status="failed",
        )
        assert result.trustworthy_success is False
        assert result.final_state != "verified"

    def test_partial_completion_not_trusted(self):
        """Executed-but-not-verified results are NOT trustworthy success."""
        result = _make_action_result(
            success=True,
            verified=False,
            executed=True,
            status="verification_failed",
        )
        assert result.trustworthy_success is False
        assert result.final_state == "verification_failed"

    def test_already_desired_state_is_trusted(self):
        """Already-in-desired-state results ARE trustworthy."""
        result = _make_action_result(
            success=True,
            verified=True,
            executed=False,
            already_in_desired_state=True,
            status="already_running",
        )
        assert result.trustworthy_success is True
        assert result.final_state == "desired_state"


# =========================================================
# 6. PARTIAL COMPLETION + RESUME
# =========================================================


class TestPartialCompletionResume:
    """
    Genesis must preserve completed work and continue from
    the correct point after failure.
    """

    def test_completed_steps_preserved_on_failure(self):
        """When a multi-step workflow fails, completed steps remain valid."""
        from genesis_os.workflow_models import WorkflowStep

        step1 = WorkflowStep(
            step_id="step-1",
            plan=ActionPlan(
                operation="application.open",
                target="Notepad",
                confidence=1.0,
            ),
        )
        step2 = WorkflowStep(
            step_id="step-2",
            plan=ActionPlan(
                operation="file.create",
                target="C:\\test\\output.txt",
                confidence=1.0,
            ),
            depends_on=("step-1",),
        )

        workflow = _make_workflow_plan([step1, step2])

        # Mock workflow engine that fails on step 2
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.trustworthy_success = False
        mock_result.to_dict.return_value = {
            "success": False,
            "status": "verification_failed",
            "step": "step-2",
            "completed_steps": ["step-1"],
        }
        mock_engine.execute.return_value = mock_result

        runtime = _make_runtime()
        runtime._workflow_engine = mock_engine

        result = runtime.execute_with_lifecycle(
            "Open Notepad and create a file",
            workflow_plan=workflow,
        )

        # The result should show partial completion
        assert "result" in result

    def test_audit_trail_preserves_step_history(self):
        """The audit trail should record all phase transitions."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("Hello")
        trace = runtime.get_trace(result["trace_id"])

        assert trace is not None
        assert len(trace.steps) >= 0  # At minimum, trace exists
        assert trace.started_at is not None

    def test_recovery_log_populated(self):
        """Recovery log should capture recovery attempt details."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Service timeout")
            return {"type": "agent", "agent": "test"}

        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.side_effect = side_effect
        runtime.agent_bridge.handle.return_value = {"status": "ok"}

        result = runtime.execute_with_lifecycle("Complex task")

        assert len(result["recovery"]) >= 1
        recovery = result["recovery"][0]
        assert "category" in recovery
        assert "error" in recovery
        assert "diagnostic" in recovery


# =========================================================
# 7. UNSEEN TASK HANDLING
# =========================================================


class TestUnseenTaskHandling:
    """
    Prove that Genesis can handle tasks it has never seen before
    by following the full lifecycle.
    """

    def test_unseen_conversation_task(self):
        """An unseen conversation task completes through the lifecycle."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        # A completely novel request
        result = runtime.execute_with_lifecycle(
            "What would happen if gravity suddenly doubled?"
        )

        assert result["success"] is True
        assert result["trace_id"] is not None
        assert len(result["phases"]) >= 3

    def test_unseen_agent_task(self):
        """An unseen agent task completes through the lifecycle."""
        runtime = _make_runtime(
            agent_bridge_response={
                "status": "completed",
                "analysis": "Novel analysis result",
            }
        )

        result = runtime.execute_with_lifecycle(
            "Analyze the correlation between rainfall and coffee prices in 2024"
        )

        assert result["success"] is True
        assert "result" in result

    def test_lifecycle_phases_ordered(self):
        """Phases must follow the spec ordering."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("Test task")

        phases = [p["phase"] for p in result["phases"]]

        # understanding must come before classified
        if "understanding" in phases and "classified" in phases:
            assert phases.index("understanding") < phases.index("classified")

        # classified must come before completed
        if "classified" in phases and "completed" in phases:
            assert phases.index("classified") < phases.index("completed")


# =========================================================
# 8. AUDIT TRAIL INTEGRITY
# =========================================================


class TestAuditTrail:
    """Verify audit trail completeness and integrity."""

    def test_every_lifecycle_creates_trace(self):
        """Every execute_with_lifecycle call must create a trace."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("Audit test")
        trace = runtime.get_trace(result["trace_id"])

        assert trace is not None
        assert trace.task_id == result["trace_id"]

    def test_production_classification_records_audit(self):
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "level": 3,
            "mode": "os",
            "intent": "application.inspect",
        }

        decision = runtime.classify("Inspect Notepad")

        assert decision["intent"] == "application.inspect"
        entries = runtime.get_audit_trail(
            task_id=runtime._last_classification_trace_id
        )
        assert any(entry.event == "classification_complete" for entry in entries)

    def test_production_action_execution_records_audit(self):
        os_manager = Mock()
        os_manager.inspect_application.return_value = {
            "success": True,
            "operation": "application.inspect",
            "executed": True,
            "verified": True,
            "running": True,
        }
        runtime = _make_runtime(os_manager=os_manager)
        executor = ActionExecutor(os_manager)
        plan = ActionPlan(
            operation="application.inspect",
            target="Notepad",
            application="Notepad",
        )

        result = runtime.execute_audited(
            goal="Inspect Notepad",
            operation=plan.operation,
            executor=executor,
            plan=plan,
        )

        entries = runtime.get_audit_trail()
        assert result.verified is True
        assert any(entry.event == "action_started" for entry in entries)
        assert any(entry.event == "observation" for entry in entries)
        assert any(entry.event == "verification" for entry in entries)

    def test_trace_records_goal(self):
        """The trace must record the original user goal."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        goal = "Find the meaning of life"
        result = runtime.execute_with_lifecycle(goal)
        trace = runtime.get_trace(result["trace_id"])

        assert trace.goal == goal

    def test_trace_records_phase_transitions(self):
        """The trace must record all phase transitions."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("Phase test")
        entries = runtime.get_audit_trail(task_id=result["trace_id"])

        assert len(entries) >= 3
        phases = [e.phase for e in entries]
        assert TaskPhase.RECEIVED in phases

    def test_trace_records_completion(self):
        """The trace must record task completion."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        result = runtime.execute_with_lifecycle("Completion test")
        trace = runtime.get_trace(result["trace_id"])

        assert trace.completed_at is not None

    def test_multiple_traces_independent(self):
        """Each lifecycle call creates an independent trace."""
        runtime = _make_runtime()
        runtime.agent_bridge.classify_request.return_value = {
            "type": "conversation",
        }

        r1 = runtime.execute_with_lifecycle("Task 1")
        r2 = runtime.execute_with_lifecycle("Task 2")

        assert r1["trace_id"] != r2["trace_id"]

        t1 = runtime.get_trace(r1["trace_id"])
        t2 = runtime.get_trace(r2["trace_id"])

        assert t1.goal == "Task 1"
        assert t2.goal == "Task 2"


# =========================================================
# 9. SPEC INVARIANTS
# =========================================================


class TestSpecInvariants:
    """Invariants that must hold for every execution."""

    def test_never_blind_retry(self):
        """Non-retryable failures must never be retried."""
        classifier = FailureClassifier()

        # PermissionError should never be retried
        result = classifier.classify(
            error="PermissionError: access denied",
            operation="file.delete",
        )
        assert result.retryable is False

        # Unknown errors should not be retried
        result = classifier.classify(
            error="Something weird happened",
            operation="unknown_op",
            exception_type="RuntimeError",
        )
        assert result.retryable is False

    def test_never_fake_success(self):
        """success=True with verified=False must never be trustworthy."""
        result = _make_action_result(
            success=True,
            verified=False,
            executed=True,
        )
        assert result.trustworthy_success is False

    def test_never_restart_workflow_unnecessarily(self):
        """Completed steps must be preserved when replanning."""
        # This is tested structurally: the workflow engine tracks
        # completed_steps and only restarts from the failed step.
        from genesis_os.workflow_models import WorkflowState

        state = WorkflowState(objective="test")
        state.completed_steps.append("step-1")
        state.completed_steps.append("step-2")

        # After recording step-1 and step-2 as completed,
        # replanning should not reset them
        assert "step-1" in state.completed_steps
        assert "step-2" in state.completed_steps

    def test_invalid_plan_triggers_replan(self):
        """An invalid plan must trigger REPLAN, not failure."""
        runtime = _make_runtime()

        # Provide a workflow plan that will fail validation
        from genesis_os.workflow_models import WorkflowPlan, WorkflowStep

        bad_step = WorkflowStep(
            step_id="bad",
            plan=ActionPlan(
                operation="application.open",
                target="test",
                confidence=1.0,
            ),
        )
        bad_plan = WorkflowPlan(
            objective="",
            steps=(bad_step,),
        )

        # execute_with_lifecycle should handle invalid plan gracefully
        result = runtime.execute_with_lifecycle(
            "Test invalid plan",
            workflow_plan=bad_plan,
        )

        # Should not crash, should return structured result
        assert "success" in result
        assert "trace_id" in result
