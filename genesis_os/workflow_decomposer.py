"""
Genesis OS — Level 3.9
Workflow Decomposition & Intent-to-Step Planning.

Responsibility:

    ObjectiveUnderstandingResult
            ↓
        Capability Requirements Resolution (via CapabilityRegistry)
            ↓
        ActionPlans (with preconditions/postconditions)
            ↓
        WorkflowSteps (with preconditions/postconditions)
            ↓
        WorkflowPlan

This module does NOT execute operating-system actions.

Execution remains exclusively mediated by:

    WorkflowPlanner
        ↓
    ExecutionSafety
        ↓
    ActionExecutor
        ↓
    OSManager

The LLM may influence the upstream understanding layer, but this
module treats the resulting intent as untrusted input and validates
it before constructing a workflow.

Level 3.9 Enhancement: Capability-driven planning - queries CapabilityRegistry
to discover capabilities matching required capabilities from understanding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List

from .action_plan import (
    ActionPlan,
    ActionPlanValidationError,
)
from .capability_registry import CapabilityRegistry
from .capability_resolver import CapabilityResolver
from .objective_understanding import (
    ObjectiveStepIntent,
    ObjectiveUnderstandingResult,
)
from .workflow_models import (
    WorkflowPlan,
    WorkflowStep,
)
from .workflow_planner import WorkflowPlanner
from .dynamic_plan import DynamicPlanConstructor

class WorkflowDecompositionError(ValueError):
    """Raised when an objective cannot safely be decomposed."""


@dataclass(frozen=True)
class DecompositionResult:
    """
    Immutable result of workflow decomposition.

    A successful result contains a validated WorkflowPlan.

    A failed result contains enough information for Genesis to
    explain why planning stopped.
    """

    objective: str

    workflow: Optional[WorkflowPlan]

    decomposed: bool

    requires_clarification: bool

    clarification_reason: Optional[str]

    step_count: int

    rejected_steps: tuple[Dict[str, Any], ...]

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def executable(self) -> bool:
        """
        True only when decomposition produced a workflow
        and no clarification is required.

        This property does NOT mean that the workflow has
        been executed.
        """

        return bool(
            self.decomposed
            and self.workflow is not None
            and not self.requires_clarification
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "decomposed": self.decomposed,
            "requires_clarification": (
                self.requires_clarification
            ),
            "clarification_reason": (
                self.clarification_reason
            ),
            "step_count": self.step_count,
            "rejected_steps": [
                dict(item)
                for item in self.rejected_steps
            ],
            "metadata": dict(self.metadata),
            "executable": self.executable,
            "workflow": (
                self.workflow.to_dict()
                if self.workflow is not None
                else None
            ),
        }


class WorkflowDecomposer:
    """
    Convert understood objective intents into a WorkflowPlan.

    Architectural boundaries:

    1. Does not parse raw natural language.
    2. Does not call the LLM.
    3. Does not execute actions.
    4. Does not bypass ActionExecutor.
    5. Does not invent missing targets.
    6. Does not silently repair unsafe intents.
    7. Does validate generated ActionPlans through the
       existing WorkflowPlanner.

    The decomposer therefore acts as a trust boundary between
    AI-generated intent and executable Genesis OS planning.

    Level 3.9: Capability-driven planning via CapabilityRegistry.
    """

    VERSION = "3.9.0"

    def __init__(
        self,
        planner: Optional[WorkflowPlanner] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
        capability_resolver: Optional[CapabilityResolver] = None,
    ):
        self.planner = (
            planner
            if planner is not None
            else WorkflowPlanner()
        )
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_resolver = (
            capability_resolver
            or CapabilityResolver(self.capability_registry)
        )
        self._dynamic_plan_constructor = (
            DynamicPlanConstructor()
        )

    # =========================================================
    # PUBLIC API
    # =========================================================

    def decompose(
        self,
        understanding: ObjectiveUnderstandingResult,
        *,
        workflow_id: str = "",
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> DecompositionResult:
        """
        Convert an understood objective into a validated
        WorkflowPlan.

        No OS operation is executed.
        """

        self._validate_input(
            understanding
        )

        result_metadata = dict(
            metadata or {}
        )

        result_metadata.update({
            "decomposition_version": self.VERSION,
            "understanding_version": (
                understanding.metadata.get(
                    "version"
                )
            ),
        })

        # -----------------------------------------------------
        # EMPTY OBJECTIVE
        # -----------------------------------------------------

        if not understanding.steps:

            return self._failure(
                understanding=understanding,
                reason=(
                    "The objective contains no "
                    "understood workflow steps."
                ),
                metadata=result_metadata,
            )

        # -----------------------------------------------------
        # UPSTREAM CLARIFICATION
        # -----------------------------------------------------

        if understanding.requires_clarification:

            rejected = tuple(
                self._intent_rejection(
                    intent
                )
                for intent in understanding.steps
                if intent.requires_clarification
            )

            return self._failure(
                understanding=understanding,
                reason=(
                    understanding.clarification_reason
                    or
                    "The objective requires clarification."
                ),
                rejected_steps=rejected,
                metadata=result_metadata,
            )

        # -----------------------------------------------------
        # RESOLVE CAPABILITIES (Level 3.9: Capability-driven planning)
        # -----------------------------------------------------
        # Query CapabilityRegistry to find concrete capabilities
        # matching the required capabilities from understanding.
        resolved_capabilities = self._resolve_capabilities(understanding)

        # -----------------------------------------------------
        # INTENT → ACTION PLAN
        # -----------------------------------------------------

        action_plans: list[ActionPlan] = []
        rejected: list[Dict[str, Any]] = []

        for intent in understanding.steps:

            try:

                action_plan = (
                    self._intent_to_action_plan(
                        intent,
                        resolved_capabilities.get(intent.step_id, [])
                    )
                )

                action_plans.append(
                    action_plan
                )

            except (
                ValueError,
                TypeError,
                ActionPlanValidationError,
            ) as error:

                rejected.append({
                    "step_id": intent.step_id,
                    "sequence": intent.sequence,
                    "text": intent.text,
                    "reason": str(error),
                })

        if rejected:

            return self._failure(
                understanding=understanding,
                reason=(
                    "One or more understood intents "
                    "could not be converted into "
                    "valid ActionPlans."
                ),
                step_count=len(
                    action_plans
                ),
                rejected_steps=tuple(
                    rejected
                ),
                metadata=result_metadata,
            )

        # -----------------------------------------------------
        # ACTION PLANS → WORKFLOW STEPS
        # -----------------------------------------------------

        try:

            workflow_steps = (
                self._build_workflow_steps(
                    action_plans,
                    understanding.steps,
                )
            )

            workflow = WorkflowPlan(
                objective=(
                    understanding.objective
                ),
                steps=tuple(
                    workflow_steps
                ),
                workflow_id=workflow_id,
                version=self.VERSION,
                metadata=result_metadata,
            )

            # -------------------------------------------------
            # AUTHORITATIVE PLANNING VALIDATION
            # -------------------------------------------------
            #
            # This is critical.
            #
            # We do NOT trust the LLM or the understanding
            # layer to decide whether a capability is
            # executable.
            #
            # WorkflowPlanner performs the existing
            # capability/safety validation.
            #

            self.planner.validate(
                workflow
            )

        except (
            ValueError,
            TypeError,
            ActionPlanValidationError,
        ) as error:

            return self._failure(
                understanding=understanding,
                reason=(
                    "The generated workflow failed "
                    "planning validation: "
                    f"{error}"
                ),
                step_count=len(
                    action_plans
                ),
                metadata=result_metadata,
            )

        return DecompositionResult(
            objective=(
                understanding.objective
            ),
            workflow=workflow,
            decomposed=True,
            requires_clarification=False,
            clarification_reason=None,
            step_count=len(
                workflow.steps
            ),
            rejected_steps=(),
            metadata=result_metadata,
        )

    # =========================================================
    # INTENT → ACTION PLAN
    # =========================================================

    def _intent_to_action_plan(
        self,
        intent: ObjectiveStepIntent,
        resolved_capabilities: Optional[List[Any]] = None,
    ) -> ActionPlan:
        """
        Convert one trusted-understanding object into an
        ActionPlan.

        The input may ultimately originate from an LLM, so
        all important fields are revalidated here.

        Level 3.9: Uses resolved capabilities for precondition/postcondition enrichment.
        """

        if intent.requires_clarification:

            raise WorkflowDecompositionError(
                f"Step '{intent.step_id}' requires "
                "clarification: "
                f"{intent.clarification_reason}"
            )

        if intent.level != 3:

            raise WorkflowDecompositionError(
                f"Step '{intent.step_id}' is not "
                "a Level 3 operation."
            )

        if intent.mode != "os":

            raise WorkflowDecompositionError(
                f"Step '{intent.step_id}' is not "
                "an OS workflow intent."
            )

        if not intent.operation:

            raise WorkflowDecompositionError(
                f"Step '{intent.step_id}' has no "
                "resolved operation."
            )

        decision = dict(
            intent.decision
        )

        # -----------------------------------------------------
        # NORMALIZE REQUIRED FIELDS
        # -----------------------------------------------------

        decision["level"] = 3
        decision["mode"] = "os"

        decision["operation"] = (
            intent.operation
        )

        decision["target"] = (
            intent.target
        )

        decision["application"] = (
            intent.application
        )

        decision["task"] = (
            intent.text
        )

        decision["confidence"] = (
            intent.confidence
        )

        decision.setdefault(
            "parameters",
            {},
        )

        # Add resolved capabilities metadata for precondition/postcondition
        if resolved_capabilities:
            decision["parameters"]["_resolved_capabilities"] = [
                {
                    "capability_id": cap.capability_id,
                    "category": getattr(cap.category, "value", str(cap.category)),
                    "supported_inputs": list(cap.supported_inputs),
                    "permissions": list(cap.permissions),
                    "metadata": cap.metadata,
                }
                for cap in resolved_capabilities
            ]

        if not isinstance(
            decision["parameters"],
            dict,
        ):
            raise WorkflowDecompositionError(
                f"Step '{intent.step_id}' has "
                "invalid parameters."
            )

        # -----------------------------------------------------
        # CREATE ACTION PLAN
        # -----------------------------------------------------

        action_plan = (
            ActionPlan.from_decision(
                decision
            )
        )

        # -----------------------------------------------------
        # ACTION PLAN VALIDATION
        # -----------------------------------------------------
        #
        # Do not wait until execution.
        #
        # Use the FULL executor-supported operation set so the
        # non-application operations (gui.*, media.*, window.*,
        # math.*, hardware.*, ...) are accepted at planning
        # time, symmetric with the single-step ActionExecutor
        # path and with WorkflowPlanner.validate().
        #

        try:
            from .action_executor import ActionExecutor as _AE
            full_ops = frozenset(_AE.SUPPORTED_OPERATIONS)
        except Exception:
            full_ops = None

        action_plan.validate(
            supported_operations=full_ops,
        )

        return action_plan

    # =========================================================
    # LEVEL 3.9: CAPABILITY RESOLUTION
    # =========================================================

    def _resolve_capabilities(
        self,
        understanding: ObjectiveUnderstandingResult,
    ) -> Dict[str, List[Any]]:
        """
        Resolve required capabilities from understanding using CapabilityRegistry.

        Returns a mapping from step_id to list of resolved CapabilityDescriptors.
        """
        resolved = {}

        # Collect all required capabilities from understanding
        all_required = set()
        for step in understanding.steps:
            all_required.update(step.required_capabilities)

        # Also include overall required capabilities
        all_required.update(understanding.required_capabilities)

        # Resolve each capability through the authoritative resolver
        for cap_id in all_required:
            resolution = self.capability_resolver.resolve_operation(
                cap_id,
                description=str(cap_id),
            )
            if not resolution.resolved:
                continue
            capability = resolution.capability
            for step in understanding.steps:
                if cap_id in step.required_capabilities:
                    if step.step_id not in resolved:
                        resolved[step.step_id] = []
                    resolved[step.step_id].append(capability)

        return resolved

    # =========================================================
    # ACTION PLANS → WORKFLOW STEPS
    # =========================================================

    @staticmethod
    def _build_workflow_steps(
        action_plans: list[ActionPlan],
        intents: tuple[
            ObjectiveStepIntent,
            ...,
        ],
    ) -> list[WorkflowStep]:
        """
        Build deterministic sequential workflow steps.

        Level 3.8.3 deliberately uses sequential dependencies.

        Parallel execution will only be introduced after the
        dependency/context model is mature enough to prove that
        two operations are genuinely independent.
        """

        if len(action_plans) != len(
            intents
        ):
            raise WorkflowDecompositionError(
                "ActionPlan and intent counts differ."
            )

        steps: list[WorkflowStep] = []

        for index, (
            action_plan,
            intent,
        ) in enumerate(
            zip(
                action_plans,
                intents,
            ),
            start=1,
        ):

            dependencies: tuple[str, ...]

            if index == 1:
                dependencies = ()

            else:
                dependencies = (
                    f"step-{index - 1}",
                )

            step = WorkflowStep(
                step_id=f"step-{index}",
                plan=action_plan,
                depends_on=dependencies,
                verification_required=True,
                max_retries=0,
                retryable=False,
                metadata={
                    "intent_step_id": (
                        intent.step_id
                    ),
                    "intent_sequence": (
                        intent.sequence
                    ),
                    "intent_text": (
                        intent.text
                    ),
                    "intent_confidence": (
                        intent.confidence
                    ),
                    "operation": (
                        action_plan.operation
                    ),
                    "target": (
                        action_plan.target
                    ),
                    "application": (
                        action_plan.application
                    ),
                },
            )

            step.validate()

            steps.append(
                step
            )

        return steps

    # =========================================================
    # VALIDATION
    # =========================================================

    @staticmethod
    def _validate_input(
        understanding: ObjectiveUnderstandingResult,
    ) -> None:

        if not isinstance(
            understanding,
            ObjectiveUnderstandingResult,
        ):
            raise TypeError(
                "WorkflowDecomposer requires an "
                "ObjectiveUnderstandingResult."
            )

        if not isinstance(
            understanding.objective,
            str,
        ):
            raise TypeError(
                "Objective must be a string."
            )

    # =========================================================
    # FAILURE HELPERS
    # =========================================================

    @staticmethod
    def _intent_rejection(
        intent: ObjectiveStepIntent,
    ) -> Dict[str, Any]:

        return {
            "step_id": intent.step_id,
            "sequence": intent.sequence,
            "text": intent.text,
            "reason": (
                intent.clarification_reason
                or
                "Intent requires clarification."
            ),
        }

    def _failure(
        self,
        *,
        understanding: ObjectiveUnderstandingResult,
        reason: str,
        metadata: Dict[str, Any],
        rejected_steps: tuple[
            Dict[str, Any],
            ...,
        ] = (),
        step_count: int = 0,
    ) -> DecompositionResult:

        return DecompositionResult(
            objective=(
                understanding.objective
            ),
            workflow=None,
            decomposed=False,
            requires_clarification=True,
            clarification_reason=reason,
            step_count=step_count,
            rejected_steps=rejected_steps,
            metadata=metadata,
        )