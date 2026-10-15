from unittest.mock import Mock

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.workflow_models import WorkflowPlan, WorkflowStep
from genesis_os.workflow_planner import WorkflowPlanner
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine


def make_engine(os_manager=None):
    return UniversalDesktopWorkflowEngine(
        ActionExecutor(os_manager or Mock())
    )


def verified_os_manager():
    os_manager = Mock()
    os_manager.inspect_application.side_effect = [
        {
            "success": True,
            "operation": "application.inspect",
            "application": "chrome",
            "executed": False,
            "verified": True,
            "running": True,
            "message": "Chrome is running.",
        },
        {
            "success": True,
            "operation": "application.inspect",
            "application": "word",
            "executed": False,
            "verified": True,
            "running": True,
            "message": "Word is running.",
        },
    ]
    return os_manager


def test_planner_converts_action_plans_to_ordered_workflow():
    workflow = WorkflowPlanner.from_action_plans(
        "inspect Chrome then Word",
        [
            ActionPlan(operation="application.inspect", target="chrome"),
            ActionPlan(operation="application.inspect", target="word"),
        ],
    )
    assert workflow.objective == "inspect Chrome then Word"
    assert [s.step_id for s in workflow.steps] == ["step-1", "step-2"]
    workflow.validate()


def test_universal_workflow_executes_sequentially_and_verifies_every_step():
    os_manager = verified_os_manager()
    engine = make_engine(os_manager)

    workflow = WorkflowPlanner.from_action_plans(
        "inspect Chrome then Word",
        [
            ActionPlan(operation="application.inspect", target="chrome"),
            ActionPlan(operation="application.inspect", target="word"),
        ],
    )

    result = engine.execute(workflow)

    assert result.success is True
    assert result.status == "completed"
    assert result.final_verified is True
    assert result.trustworthy_success is True
    assert result.state["completed_steps"] == ["step-1", "step-2"]
    assert len(result.steps) == 2
    assert all(step["trustworthy_success"] for step in result.steps)
    assert os_manager.inspect_application.call_args_list[0].args == ("chrome",)
    assert os_manager.inspect_application.call_args_list[1].args == ("word",)


def test_workflow_stops_at_confirmation_and_preserves_prior_evidence():
    os_manager = Mock()
    os_manager.inspect_application.return_value = {
        "success": True,
        "operation": "application.inspect",
        "application": "chrome",
        "executed": False,
        "verified": True,
        "running": True,
    }
    engine = make_engine(os_manager)

    workflow = WorkflowPlan(
        objective="inspect Chrome then delete a file",
        steps=(
            WorkflowStep(
                "inspect",
                ActionPlan(operation="application.inspect", target="chrome"),
            ),
            WorkflowStep(
                "delete",
                ActionPlan(operation="file.delete", target="important.txt"),
            ),
        ),
    )

    result = engine.execute(workflow)

    assert result.success is False
    assert result.status == "confirmation_required"
    assert result.state["completed_steps"] == ["inspect"]
    assert len(result.steps) == 2
    assert os_manager.inspect_application.call_count == 1


def test_observation_failure_cannot_promote_execution():
    class BrokenObservation:
        def observe(self, *args, **kwargs):
            raise RuntimeError("observation backend unavailable")

    os_manager = Mock()
    os_manager.inspect_application.return_value = {
        "success": True,
        "running": True,
        "application": "chrome",
    }
    executor = ActionExecutor(os_manager)
    engine = UniversalDesktopWorkflowEngine(executor)
    engine._observation_loop = BrokenObservation()
    workflow = WorkflowPlanner.from_action_plans(
        "inspect Chrome",
        [ActionPlan(operation="application.inspect", target="chrome")],
    )

    result = engine.execute(workflow)

    assert result.success is False
    assert result.status == "verification_failed"
    assert result.final_verified is False
    assert result.steps[-1]["error"] == "observation backend unavailable"



def test_workflow_does_not_claim_success_when_verification_fails():
    os_manager = Mock()
    os_manager.inspect_application.return_value = {
        "success": True,
        "operation": "application.inspect",
        "application": "chrome",
        "executed": True,
        "verified": False,
        "message": "Inspection returned but state was not verified.",
    }
    result = make_engine(os_manager).execute(
        WorkflowPlanner.from_action_plans(
            "inspect Chrome",
            [ActionPlan(operation="application.inspect", target="chrome")],
        )
    )
    assert result.success is False
    assert result.final_verified is False
    assert result.trustworthy_success is False
    assert result.status == "verification_failed"


def test_workflow_rejects_unknown_capability_before_execution():
    os_manager = Mock()
    workflow = WorkflowPlan(
        objective="unsupported operation",
        steps=(
            WorkflowStep(
                "unknown",
                ActionPlan.model_construct(
                    operation="unknown.operation",
                    target="x",
                ),
            ),
        ),
    )
    result = make_engine(os_manager).execute(workflow)
    assert result.success is False
    assert result.status == "invalid_plan"
    assert os_manager.method_calls == []


def test_dependencies_are_enforced():
    workflow = WorkflowPlan(
        objective="dependent workflow",
        steps=(
            WorkflowStep("one", ActionPlan("application.inspect", "chrome")),
            WorkflowStep(
                "two",
                ActionPlan("application.inspect", "word"),
                depends_on=("missing",),
            ),
        ),
    )
    result = make_engine().execute(workflow)
    assert result.success is False
    assert result.status == "invalid_plan"


def test_explicit_retry_policy_can_retry_verification_failure():
    os_manager = Mock()
    os_manager.inspect_application.side_effect = [
        {
            "success": True,
            "operation": "application.inspect",
            "application": "chrome",
            "executed": True,
            "verified": False,
        },
        {
            "success": True,
            "operation": "application.inspect",
            "application": "chrome",
            "executed": False,
            "verified": True,
            "running": True,
        },
    ]
    workflow = WorkflowPlan(
        objective="retryable inspection",
        steps=(
            WorkflowStep(
                "inspect",
                ActionPlan("application.inspect", "chrome"),
                retryable=True,
                max_retries=1,
            ),
        ),
    )
    result = make_engine(os_manager).execute(workflow)
    assert result.success is True
    assert len(result.steps) == 2
    assert os_manager.inspect_application.call_count == 2
