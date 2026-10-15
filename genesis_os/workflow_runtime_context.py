"""
Genesis OS — Level 3.8.5 unified runtime context.

Combines:

    WorkflowContext
    WorkflowStateStore
    WorkflowDataBinder
    WorkflowContextPropagator

into one runtime-level facade.

This is orchestration state, not execution.
"""

from __future__ import annotations

from .workflow_binding import (
    WorkflowDataBinder,
)

from .workflow_context import (
    WorkflowContext,
)

from .workflow_context_propagator import (
    WorkflowContextPropagator,
)

from .workflow_state import (
    WorkflowStateStore,
)
from .capability_registry import (
    CapabilityRegistry,
)

from .capability_resolver import (
    CapabilityResolver,
)
from .default_capabilities import (
    register_default_capabilities,
)


from .workflow_capability import (
    WorkflowCapabilityResolver,
)
from .dynamic_plan import DynamicPlanConstructor

class WorkflowRuntimeContext:

    VERSION = "3.8.5"

    def __init__(
        self,
        workflow_id: str,
    ) -> None:

        self.workflow_id = workflow_id

        self.context = (
            WorkflowContext(
                workflow_id=workflow_id
            )
        )

        self.state = (
            WorkflowStateStore(
                workflow_id
            )
        )

        self.binder = (
            WorkflowDataBinder(
                self.context
            )
        )

        self.propagator = (
            WorkflowContextPropagator(
                self.context
            )
        )
        self.capability_registry = (
            CapabilityRegistry()
        )

        register_default_capabilities(
            self.capability_registry
        )

        self.capability_resolver = (
            CapabilityResolver(
                self.capability_registry
            )
        )

        self.workflow_capability_resolver = (
            WorkflowCapabilityResolver(
                self.capability_resolver
            )
        )

    def register_workflow(
        self,
        workflow,
    ) -> None:

        for step in workflow.steps:

            self.state.register_step(
                step.step_id
            )

    def prepare_step(
        self,
        step,
    ):

        from .workflow_context_runtime import (
            WorkflowContextRuntime,
        )

        runtime = (
            WorkflowContextRuntime(
                self.context,
                self.state,
            )
        )

        return runtime.prepare_step(
            step
        )

    def record_action_result(
        self,
        step_id: str,
        action_result,
    ) -> None:

        self.propagator.propagate(
            step_id=step_id,
            action_result=action_result,
        )

    def snapshot(self):

        return {
            "workflow_id": self.workflow_id,
            "version": self.VERSION,
            "context": (
                self.context.to_dict()
            ),
            "state": {
                "version": (
                    self.state.version
                ),
                "status": (
                    self.state.status.value
                ),
                "active_step_id": (
                    self.state.active_step_id
                ),
            },
        }
    def resolve_capability(
        self,
        *,
        step_id: str,
        requirement,
        ):
        return (
            self.workflow_capability_resolver
            .resolve_step(
                step_id=step_id,
                requirement=requirement,
            )
        )