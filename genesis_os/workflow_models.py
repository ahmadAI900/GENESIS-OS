"""Genesis OS — Level 3.8 workflow state contracts.

These models describe an objective-level desktop workflow without executing
anything. Execution remains mediated by ActionExecutor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from .action_plan import ActionPlan


WORKFLOW_STATUSES = frozenset({
    "pending",
    "planning",
    "planned",
    "running",
    "verified",
    "already_in_desired_state",
    "confirmation_required",
    "failed",
    "verification_failed",
    "invalid_step",
    "blocked",
    "completed",
})


@dataclass(frozen=True)
class WorkflowStep:
    """One independently executable and verifiable workflow step."""

    step_id: str
    plan: ActionPlan
    depends_on: tuple[str, ...] = ()
    verification_required: bool = True
    max_retries: int = 0
    retryable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.step_id, str) or not self.step_id.strip():
            raise ValueError("WorkflowStep step_id must be a non-empty string.")
        if not isinstance(self.plan, ActionPlan):
            raise TypeError("WorkflowStep plan must be an ActionPlan.")
        if any(not isinstance(item, str) or not item.strip() for item in self.depends_on):
            raise ValueError("WorkflowStep dependencies must be non-empty strings.")
        if self.max_retries < 0:
            raise ValueError("WorkflowStep max_retries cannot be negative.")
        if self.retryable and self.max_retries == 0:
            raise ValueError("A retryable step must allow at least one retry.")
        if not isinstance(self.metadata, dict):
            raise TypeError("WorkflowStep metadata must be a dictionary.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "plan": self.plan.to_dict(),
            "depends_on": list(self.depends_on),
            "verification_required": self.verification_required,
            "max_retries": self.max_retries,
            "retryable": self.retryable,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorkflowPlan:
    """Immutable objective-level plan.

    The plan is declarative. It contains no executable callback and cannot
    bypass ActionExecutor.
    """

    objective: str
    steps: tuple[WorkflowStep, ...]
    workflow_id: str = ""
    version: str = "3.8.3"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("WorkflowPlan objective must be non-empty.")
        if not self.steps:
            raise ValueError("WorkflowPlan must contain at least one step.")
        if not isinstance(self.metadata, dict):
            raise TypeError("WorkflowPlan metadata must be a dictionary.")

        ids = set()
        for step in self.steps:
            step.validate()
            if step.step_id in ids:
                raise ValueError(f"Duplicate workflow step id: {step.step_id}")
            ids.add(step.step_id)

        for step in self.steps:
            unknown = set(step.depends_on) - ids
            if unknown:
                raise ValueError(
                    f"Workflow step '{step.step_id}' has unknown dependencies: "
                    f"{sorted(unknown)}"
                )
            if step.step_id in step.depends_on:
                raise ValueError(f"Workflow step '{step.step_id}' cannot depend on itself.")

        # Dependencies must point backward in the declarative sequence.
        positions = {step.step_id: index for index, step in enumerate(self.steps)}
        for step in self.steps:
            for dependency in step.depends_on:
                if positions[dependency] >= positions[step.step_id]:
                    raise ValueError(
                        f"Workflow dependency '{dependency}' must precede "
                        f"step '{step.step_id}'."
                    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "objective": self.objective,
            "version": self.version,
            "steps": [step.to_dict() for step in self.steps],
            "metadata": dict(self.metadata),
        }


@dataclass
class WorkflowState:
    """Mutable runtime state and evidence for one workflow execution."""

    objective: str
    status: str = "pending"
    current_step: Optional[str] = None
    completed_steps: list[str] = field(default_factory=list)
    failed_step: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    evidence: list[Dict[str, Any]] = field(default_factory=list)
    errors: list[Dict[str, Any]] = field(default_factory=list)
    replans: int = 0

    def record(self, step_id: str, result: Dict[str, Any]) -> None:
        self.evidence.append({
            "step_id": step_id,
            "result": dict(result),
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "status": self.status,
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "failed_step": self.failed_step,
            "context": dict(self.context),
            "evidence": list(self.evidence),
            "errors": list(self.errors),
            "replans": self.replans,
        }


@dataclass(frozen=True)
class WorkflowResult:
    """Final, user-safe aggregate result."""

    success: bool
    status: str
    objective: str
    steps: tuple[Dict[str, Any], ...]
    state: Dict[str, Any]
    final_verified: bool
    message: str
    error: Optional[str] = None

    @property
    def trustworthy_success(self) -> bool:
        return bool(self.success and self.final_verified)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "trustworthy_success": self.trustworthy_success,
            "status": self.status,
            "objective": self.objective,
            "steps": list(self.steps),
            "state": dict(self.state),
            "final_verified": self.final_verified,
            "message": self.message,
            "error": self.error,
        }
