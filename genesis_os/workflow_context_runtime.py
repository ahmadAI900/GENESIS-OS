"""
Genesis OS — Level 3.8.5
Context-aware workflow runtime preparation.

This component prepares a workflow step for execution.

It does NOT execute the step.

Responsibilities:

    1. Check dependency state.
    2. Resolve data bindings.
    3. Validate the resulting ActionPlan.
    4. Return the execution-ready plan.

Actual execution remains with ActionExecutor.
"""

from __future__ import annotations

from dataclasses import replace


from .workflow_context import (
    WorkflowContext,
)
from .workflow_binding import WorkflowDataBinder
from .workflow_state import (
    StepRuntimeStatus,
    WorkflowStateStore,
)


class WorkflowContextRuntime:

    VERSION = "3.8.5"

    def __init__(
        self,
        context: WorkflowContext,
        state: WorkflowStateStore,
    ) -> None:

        self.context = context
        self.state = state
        self.binder = WorkflowDataBinder(context)

    def prepare_step(
        self,
        step,
    ):
        """
        Prepare a WorkflowStep for execution.

        No execution occurs here.
        """

        self._validate_dependencies(
            step
        )

        bound_plan = (
            self.binder.validate_bound_plan(
                step.plan
            )
        )

        return replace(
            step,
            plan=bound_plan,
            metadata={
                **step.metadata,
                "context_version": (
                    self.context.version
                ),
                "context_runtime_version": (
                    self.VERSION
                ),
            },
        )

    def _validate_dependencies(
        self,
        step,
    ) -> None:

        for dependency_id in (
            step.depends_on
        ):

            dependency = (
                self.state.get_step(
                    dependency_id
                )
            )

            if dependency.status not in {
                StepRuntimeStatus.SUCCEEDED,
                StepRuntimeStatus.VERIFIED,
                StepRuntimeStatus.ALREADY_SATISFIED,
            }:

                raise RuntimeError(
                    f"Step '{step.step_id}' "
                    f"cannot execute because "
                    f"dependency "
                    f"'{dependency_id}' is "
                    f"not complete."
                )