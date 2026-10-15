"""Genesis OS — Level 3.8 workflow planning and preflight."""
from __future__ import annotations

from typing import Iterable, Optional

from .action_plan import ActionPlan
from .capability_registry import CapabilityRegistry
from .execution_safety import ExecutionSafety
from .workflow_models import WorkflowPlan, WorkflowStep


def _full_supported_operations() -> frozenset:
    """Return the full set of supported operations.

    The single-step ActionExecutor accepts non-application
    operations (media.*, window.*, math.*, hardware.*, etc.)
    that are not in the strict ``APPLICATION_OPERATIONS`` set
    used by ``ActionPlan.validate()`` by default. To keep
    workflow planning symmetric with the single-step path, the
    planner uses the executor's full set when it preflights
    each step's plan.
    """
    try:
        from .action_executor import ActionExecutor
        return frozenset(ActionExecutor.SUPPORTED_OPERATIONS)
    except Exception:
        return frozenset()


class WorkflowPlanner:
    """Build and validate reusable objective-level plans.

    This class deliberately does not infer user intent or execute actions.
    Higher-level objective understanding can supply ActionPlans here.
    """

    VERSION = "3.8.2"

    @staticmethod
    def from_action_plans(
        objective: str,
        plans: Iterable[ActionPlan],
        *,
        workflow_id: str = "",
    ) -> WorkflowPlan:
        plan_list = list(plans or [])
        if not plan_list:
            raise ValueError("At least one ActionPlan is required.")

        steps = tuple(
            WorkflowStep(
                step_id=f"step-{index}",
                plan=plan,
            )
            for index, plan in enumerate(plan_list, start=1)
        )
        workflow = WorkflowPlan(
            objective=objective,
            steps=steps,
            workflow_id=workflow_id,
        )
        WorkflowPlanner.validate(workflow)
        return workflow

    @staticmethod
    def validate(workflow: WorkflowPlan) -> None:
        workflow.validate()


        full_ops = _full_supported_operations()
        for step in workflow.steps:
            step.validate()
            # Use the full executor-supported operation set so
            # non-application operations (media.*, window.*,
            # math.*, hardware.*, etc.) are accepted here just
            # as the single-step ActionExecutor accepts them.
            step.plan.validate(
                supported_operations=full_ops or None,
            )
            operation = step.plan.operation
            if not CapabilityRegistry.exists(operation):
                raise ValueError(
                    f"Workflow step '{step.step_id}' references unknown "
                    f"capability: {operation}"
                )

            decision = ExecutionSafety.check(operation)
            if not decision.allowed:
                raise ValueError(
                    f"Workflow step '{step.step_id}' is not executable: "
                    f"{decision.status} — {decision.reason}"
                )
