"""Genesis OS — verified multi-step desktop workflow executor.

Level 3.8

This layer does not bypass ActionExecutor. Every step is independently
validated and safety-checked. A workflow stops at the first failed,
confirmation-required, or unverified step.
"""
from __future__ import annotations
from typing import Iterable
from .action_plan import ActionPlan
from .action_executor import ActionExecutor


class DesktopWorkflowExecutor:
    VERSION = "3.8.1"

    def __init__(self, action_executor: ActionExecutor):
        if action_executor is None:
            raise ValueError("DesktopWorkflowExecutor requires an ActionExecutor.")
        self.executor = action_executor

    def execute(self, plans: Iterable[ActionPlan]) -> dict:
        plans = list(plans or [])
        results = []
        if not plans:
            return {"success": False, "status": "empty_workflow", "steps": []}

        for index, plan in enumerate(plans, start=1):
            if not isinstance(plan, ActionPlan):
                return {"success": False, "status": "invalid_step", "step": index, "steps": results}
            result = self.executor.execute(plan)
            results.append({"step": index, "result": result.to_dict()})
            if result.status == "confirmation_required":
                return {"success": False, "status": "confirmation_required", "step": index, "steps": results}
            if not result.success or not result.verified:
                return {"success": False, "status": "step_failed", "step": index, "steps": results}

        return {"success": True, "status": "verified", "step_count": len(results), "steps": results}
