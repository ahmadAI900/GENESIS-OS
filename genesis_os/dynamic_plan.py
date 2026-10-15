"""
Genesis OS — Level 3.8.7

Dynamic Plan Construction.

Purpose
-------

Convert an already-resolved workflow capability into the
canonical Genesis ActionPlan.

Architecture:

    WorkflowStep
        +
    WorkflowCapabilityBinding
        +
    WorkflowContext
        ↓
    DynamicPlanConstructor
        ↓
    ActionPlan
        ↓
    Safety
        ↓
    ActionExecutor

IMPORTANT:

This module NEVER executes an operating-system action.

It only constructs a validated ActionPlan.

The existing ActionExecutor remains the sole execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from .action_plan import (
    ActionPlan,
    ActionPlanValidationError,
)

from .capability_resolution import (
    CapabilityResolutionStatus,
)
from .workflow_capability import (
    WorkflowCapabilityBinding,
)

from .workflow_context import (
    WorkflowContext,
)


# ============================================================
# ERRORS
# ============================================================


class DynamicPlanConstructionError(
    RuntimeError
):
    """
    Base error for dynamic plan construction.
    """


class CapabilityNotResolvedError(
    DynamicPlanConstructionError
):
    """
    Raised when a workflow step has no usable capability.
    """


class DynamicPlanValidationError(
    DynamicPlanConstructionError
):
    """
    Raised when the generated ActionPlan violates the
    established Level 3 execution contract.
    """


# ============================================================
# RESULT CONTRACT
# ============================================================


@dataclass(frozen=True)
class DynamicPlanResult:
    """
    Result of dynamic plan construction.

    The result deliberately separates:

        constructed
        plan
        explanation
        metadata

    so callers never need to infer whether construction
    actually succeeded.
    """

    constructed: bool

    plan: Optional[ActionPlan]

    step_id: str

    capability_id: Optional[str]

    provider: Optional[str]

    confidence: float

    explanation: str

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def operation(self) -> Optional[str]:
        if self.plan is None:
            return None

        return self.plan.operation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constructed": self.constructed,
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "provider": self.provider,
            "confidence": self.confidence,
            "operation": self.operation,
            "plan": (
                self.plan.to_dict()
                if self.plan is not None
                else None
            ),
            "explanation": self.explanation,
            "metadata": dict(self.metadata),
        }


# ============================================================
# CONSTRUCTOR
# ============================================================


class DynamicPlanConstructor:
    """
    Level 3.8.7 dynamic ActionPlan constructor.

    Responsibilities:

        1. validate capability resolution
        2. resolve workflow context bindings
        3. preserve the workflow target
        4. preserve application identity
        5. merge capability metadata
        6. construct ActionPlan
        7. validate ActionPlan

    It does NOT:

        - execute
        - launch applications
        - close applications
        - modify files
        - call OSManager
        - call ActionExecutor
    """

    VERSION = "3.8.7"

    def construct(
        self,
        *,
        step_id: str,
        binding: WorkflowCapabilityBinding,
        workflow_context: Optional[
            WorkflowContext
        ] = None,
        target: Optional[str] = None,
        application: Optional[str] = None,
        parameters: Optional[
            Mapping[str, Any]
        ] = None,
        task: str = "",
        reason: str = "",
        source: str = "DynamicPlanConstructor",
    ) -> DynamicPlanResult:
        """
        Construct one ActionPlan from one resolved capability.
        """

        if not isinstance(
            step_id,
            str,
        ) or not step_id.strip():

            raise DynamicPlanConstructionError(
                "step_id must be a non-empty string."
            )

        if not isinstance(
            binding,
            WorkflowCapabilityBinding,
        ):
            raise TypeError(
                "binding must be a "
                "WorkflowCapabilityBinding."
            )

        resolved = binding.resolved

        # ----------------------------------------------------
        # RESOLUTION GATE
        # ----------------------------------------------------

        if (
            resolved.status
            != CapabilityResolutionStatus.RESOLVED
            or resolved.capability is None
        ):
            raise CapabilityNotResolvedError(
                "Cannot construct an ActionPlan because "
                f"capability resolution status is "
                f"'{resolved.status.value}'."
            )

        capability = resolved.capability

        capability_id = (
            capability.capability_id
        )

        provider = capability.provider

        # ----------------------------------------------------
        # CONFIDENCE
        # ----------------------------------------------------

        confidence = float(
            resolved.confidence
        )

        if not 0.0 <= confidence <= 1.0:
            raise DynamicPlanValidationError(
                "Resolved capability confidence must "
                "be between 0 and 1."
            )

        # ----------------------------------------------------
        # TARGET RESOLUTION
        # ----------------------------------------------------

        resolved_target = self._resolve_target(
            target=target,
            binding=binding,
            workflow_context=(
                workflow_context
            ),
        )

        resolved_application = (
            self._resolve_application(
                application=application,
                binding=binding,
                workflow_context=(
                    workflow_context
                ),
            )
        )

        # ----------------------------------------------------
        # PARAMETERS
        # ----------------------------------------------------

        plan_parameters = dict(
            parameters or {}
        )

        self._inject_capability_metadata(
            plan_parameters=plan_parameters,
            capability=capability,
        )

        # ----------------------------------------------------
        # TARGET → REQUIRED CAPABILITY INPUTS
        # ----------------------------------------------------

        self._populate_required_inputs(
            plan_parameters=plan_parameters,
            capability=capability,
            target=resolved_target,
            application=resolved_application,
        )
        self._validate_required_inputs(
            binding=binding,
            parameters=plan_parameters,
        )

        # ----------------------------------------------------
        # ACTION PLAN
        # ----------------------------------------------------

        plan = ActionPlan(
            operation=capability.operation,
            target=resolved_target,
            application=resolved_application,
            task=task,
            confidence=confidence,
            parameters=plan_parameters,
            reason=(
                reason
                or resolved.explanation
                or (
                    f"Capability '{capability_id}' "
                    "resolved dynamically."
                )
            ),
            source=source,
        )

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        try:

            plan.validate()

        except (
            ActionPlanValidationError,
            ValueError,
            TypeError,
        ) as error:

            raise DynamicPlanValidationError(
                "Dynamic plan construction produced an "
                f"invalid ActionPlan: {error}"
            ) from error

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        return DynamicPlanResult(
            constructed=True,
            plan=plan,
            step_id=step_id,
            capability_id=capability_id,
            provider=provider,
            confidence=confidence,
            explanation=(
                f"Dynamic ActionPlan constructed from "
                f"capability '{capability_id}'."
            ),
            metadata={
                "version": self.VERSION,
                "capability_category": (
                    getattr(
                        capability.category,
                        "value",
                        str(
                            capability.category
                        ),
                    )
                ),
                "capability_operation": (
                    capability.operation
                ),
                "dangerous": (
                    capability.dangerous
                ),
                "requires_confirmation": (
                    resolved.requires_confirmation
                ),
                "resolution_status": (
                    resolved.status.value
                ),
            },
        )

    # ========================================================
    # TARGET
    # ========================================================

    @staticmethod
    def _resolve_target(
        *,
        target: Optional[str],
        binding: WorkflowCapabilityBinding,
        workflow_context: Optional[
            WorkflowContext
        ],
    ) -> Optional[str]:
        """
        Resolve the target without guessing.

        Explicit target wins.

        Otherwise Genesis may use workflow context.

        No fuzzy guessing occurs here.
        """

        if target is not None:

            if not isinstance(
                target,
                str,
            ):
                raise DynamicPlanValidationError(
                    "Dynamic plan target must be a string."
                )

            if not target.strip():
                raise DynamicPlanValidationError(
                    "Dynamic plan target cannot be empty."
                )

            return target.strip()

        requirement = (
            binding.requirement
        )

        metadata = (
            requirement.metadata
            or {}
        )

        context_key = metadata.get(
            "target_context_key"
        )

        if (
            context_key
            and workflow_context is not None
        ):

            value = workflow_context.get(
                context_key
            )

            if value is None:
                raise DynamicPlanValidationError(
                    "Required target context value "
                    f"'{context_key}' is unavailable."
                )

            return str(value)

        return None

    # ========================================================
    # APPLICATION
    # ========================================================

    @staticmethod
    def _resolve_application(
        *,
        application: Optional[str],
        binding: WorkflowCapabilityBinding,
        workflow_context: Optional[
            WorkflowContext
        ],
    ) -> Optional[str]:
        """
        Resolve application identity.

        Explicit application identity wins.

        Context can provide it when the requirement
        explicitly declares the context key.
        """

        if application is not None:

            if not isinstance(
                application,
                str,
            ):
                raise DynamicPlanValidationError(
                    "Application must be a string."
                )

            if not application.strip():
                raise DynamicPlanValidationError(
                    "Application cannot be empty."
                )

            return application.strip()

        metadata = (
            binding.requirement.metadata
            or {}
        )

        context_key = metadata.get(
            "application_context_key"
        )

        if (
            context_key
            and workflow_context is not None
        ):

            value = workflow_context.get(
                context_key
            )

            if value is None:
                raise DynamicPlanValidationError(
                    "Required application context "
                    f"value '{context_key}' is unavailable."
                )

            return str(value)

        return None

    # ========================================================
    # CAPABILITY METADATA
    # ========================================================

    @staticmethod
    def _inject_capability_metadata(
        *,
        plan_parameters: Dict[str, Any],
        capability: Any,
    ) -> None:
        """
        Preserve capability identity in the plan.

        The executor still receives the canonical ActionPlan
        operation. These metadata fields are informational
        and must never be interpreted as executable callbacks.
        """

        plan_parameters.setdefault(
            "_capability_id",
            capability.capability_id,
        )

        plan_parameters.setdefault(
            "_capability_provider",
            capability.provider,
        )

        plan_parameters.setdefault(
            "_capability_version",
            capability.version,
        )

    # ========================================================
    # REQUIRED INPUTS
    # ========================================================

    @staticmethod
    def _populate_required_inputs(
        *,
        plan_parameters: Dict[str, Any],
        capability: Any,
        target: Optional[str],
        application: Optional[str],
    ) -> None:
        """
        Populate only deterministic capability inputs.

        Genesis must never invent values for required inputs.
        """

        required = set(
            capability.supported_inputs
        )

        if (
            "application" in required
            and application is not None
        ):
            plan_parameters.setdefault(
                "application",
                application,
            )

        if (
            "path" in required
            and target is not None
        ):
            plan_parameters.setdefault(
                "path",
                target,
            )

        if (
            "target" in required
            and target is not None
        ):
            plan_parameters.setdefault(
                "target",
                target,
            )
    @staticmethod
    def _validate_required_inputs(
        *,
        binding: WorkflowCapabilityBinding,
        parameters: Dict[str, Any],
    ) -> None:
        """
        Ensure every required workflow input is present.

        A capability must never receive a dynamically fabricated
        value.
        """

        required = set(
            binding.requirement.required_inputs
        )

        missing = sorted(
            item
            for item in required
            if item not in parameters
        )

        if missing:
            raise DynamicPlanValidationError(
                "Dynamic ActionPlan is missing required "
                f"inputs: {missing}"
            )