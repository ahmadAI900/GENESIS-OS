"""
Genesis OS — Level 3.8.4 Workflow Target Resolution.

Binds dynamically resolved real-world targets to workflow
ActionPlans.

This layer does not execute actions.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from .target_discovery import (
    TargetDiscovery,
)
from .target_models import (
    TargetResolutionResult,
)
from .workflow_models import (
    WorkflowPlan,
)
from .workflow_context import (
    WorkflowContext,
)

from .workflow_state import (
    WorkflowStateStore,
)

class WorkflowTargetResolver:
    """
    Resolve targets for every workflow step that requires
    dynamic discovery.

    The original WorkflowPlan is never mutated in-place.
    """

    VERSION = "3.8.4"

    # Operations whose target is a natural-language description
    # of an EXISTING file or folder. Operations that create new
    # targets (folder.create, file.create) and operations that
    # own their target resolution internally (application.*,
    # browser.*, system.*) must never pass through generic
    # discovery: their targets are names, queries, or URLs, not
    # resolvable filesystem objects.
    RESOLVABLE_OPERATIONS = frozenset({
        "folder.open",
        "folder.inspect",
        "folder.organize",
        "file.open",
        "file.inspect",
        "file.read",
        "file.hash",
        "file.copy",
        "file.move",
        "file.rename",
    })

    def __init__(
        self,
        target_discovery,
        *,
        context=None,
        state=None,
    ):
        self.target_discovery = (
            target_discovery
        )

        self.context = context

        self.state = state
        

    def resolve_workflow(
        self,
        workflow: WorkflowPlan,
    ):

        results: Dict[
            str,
            TargetResolutionResult,
        ] = {}

        updated_steps = []

        for step in workflow.steps:

            action_plan = step.plan

            # Only genuinely semantic filesystem targets are
            # resolved here. Everything else keeps its plan
            # target untouched.
            if (
                not action_plan.target
                or action_plan.operation
                not in self.RESOLVABLE_OPERATIONS
            ):

                updated_steps.append(
                    step
                )

                continue

            query = (
                self.target_discovery
                .build_query_from_action_plan(
                    action_plan
                )
            )

            result = (
                self.target_discovery
                .discover_and_resolve(
                    query,
                    context=self.context,
                )
            )

            results[
                step.step_id
            ] = result

            if not result.successful:

                return (
                    None,
                    results,
                )

            resolved = result.resolved

            assert resolved is not None

            updated_plan = replace(
                action_plan,
                target=resolved.value,
            )

            updated_step = replace(
                step,
                plan=updated_plan,
                metadata={
                    **step.metadata,
                    "target_resolution": (
                        resolved.to_dict()
                    ),
                    "target_resolution_version": (
                        self.VERSION
                    ),
                },
            )

            updated_steps.append(
                updated_step
            )

        updated_workflow = replace(
            workflow,
            steps=tuple(
                updated_steps
            ),
            metadata={
                **workflow.metadata,
                "target_resolution_version": (
                    self.VERSION
                ),
            },
        )

        return (
            updated_workflow,
            results,
        )