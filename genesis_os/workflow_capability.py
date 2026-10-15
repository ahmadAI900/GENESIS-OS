"""
Genesis OS — Level 3.8.6
Workflow Capability Binding.

Connects a WorkflowStep to the capability required to
execute that step.

This is a planning concern.

It does not execute the capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .capabilities import (
    CapabilityRequirement,
)

from .capability_resolution import (
    ResolvedCapability,
)

from .capability_resolver import (
    CapabilityResolver,
)


@dataclass(frozen=True)
class WorkflowCapabilityBinding:
    step_id: str

    requirement: CapabilityRequirement

    resolved: ResolvedCapability

    metadata: Dict[str, Any]


class WorkflowCapabilityResolver:

    VERSION = "3.8.6"

    def __init__(
        self,
        resolver: CapabilityResolver,
    ) -> None:

        self.resolver = resolver
        from .dynamic_plan import DynamicPlanConstructor
        self._plan_constructor = (
            DynamicPlanConstructor()
        )

    def resolve_step(
        self,
        *,
        step_id: str,
        requirement: CapabilityRequirement,
    ) -> WorkflowCapabilityBinding:

        resolved = self.resolver.resolve(
            requirement
        )

        capability = resolved.capability

        metadata = {
            "resolver_version": self.VERSION,
            "resolution_status": (
                resolved.status.value
            ),
            "confidence": (
                resolved.confidence
            ),
        }

        if capability is not None:

            metadata.update({
                "capability_id": (
                    capability.capability_id
                ),
                "provider": (
                    capability.provider
                ),
                "operation": (
                    capability.operation
                ),
            })

        return WorkflowCapabilityBinding(
            step_id=step_id,
            requirement=requirement,
            resolved=resolved,
            metadata=metadata,
        )
    def construct_plan(
        self,
        *,
        step_id: str,
        requirement: CapabilityRequirement,
        target: str | None = None,
        application: str | None = None,
        parameters: dict | None = None,
        task: str = "",
        reason: str = "",
        workflow_context=None,
    ):
        """
        Resolve a workflow capability and construct the
        canonical ActionPlan.

        This method performs planning only.

        It NEVER executes the resulting plan.
        """

        binding = self.resolve_step(
            step_id=step_id,
            requirement=requirement,
        )

        return self._plan_constructor.construct(
            step_id=step_id,
            binding=binding,
            workflow_context=workflow_context,
            target=target,
            application=application,
            parameters=parameters,
            task=task,
            reason=reason,
        )