"""
Genesis OS — Compound Task Router.

Architectural role
------------------
This module is the missing bridge between
    WorkflowDecisionEngine (per-request L3 decision)
and
    UniversalDesktopWorkflowEngine (multi-step workflow executor)
for compound natural-language tasks such as
    "open chrome, go to github, and search for repos about langchain"
    "minimize all windows and then open the task manager"
    "open my downloads then move the latest PDF to my desktop".

Why this module exists
----------------------
WorkflowDecisionEngine.decide() returns a SINGLE
(level, mode, intent) tuple. For single-step requests this is
correct. For multi-step compound requests this collapses
multiple real actions into one and silently drops the rest.

ObjectiveUnderstanding already splits compound NL into a list
of step intents and WorkflowDecomposer already produces a
validated WorkflowPlan. The existing pieces are correct;
they were simply never wired into run_level3.

What this module does
---------------------
1. ``CompoundTaskDetector`` is a deterministic, meaning-based
   detector: it asks ObjectiveUnderstanding for a step list and
   checks whether the request is genuinely compound (>=2 fully
   Level-3 executable steps) versus a single action.

2. ``build_workflow_plan_from_understanding`` adapts the
   ObjectiveUnderstandingResult into the WorkflowPlan shape
   the UniversalDesktopWorkflowEngine already accepts.

3. ``CompoundTaskRouter`` is the orchestrator: it tries the
   compound path first; if the request is not compound, it
   returns None and the caller falls through to the existing
   single-step run_level3 path.

Architectural invariants
------------------------
* No step bypasses ActionExecutor. Every step in the produced
  WorkflowPlan is dispatched through the same
  UniversalDesktopWorkflowEngine used by the Level 3.8 path.
* No new capability is invented. Only registered capabilities
  appear in the produced plan.
* Single-step L3 requests remain on the existing single-shot
  ActionExecutor.execute() path; the compound path is purely
  additive.
* WorkflowDecisionEngine is untouched. This module is a
  consumer of it, not a competitor.

Spec compliance
---------------
* The detector is meaning-based, not a list of hard-coded
  sentences.
* The fix is measured: every previously-passing single-step
  task still routes to the same single-step executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from genesis_os.objective_understanding import (
    ObjectiveUnderstanding,
    ObjectiveUnderstandingResult,
)
from genesis_os.workflow_models import (
    WorkflowPlan,
    WorkflowStep,
    WorkflowResult,
)
from genesis_os.workflow_decomposer import (
    WorkflowDecomposer,
    DecompositionResult,
)
from genesis_os.action_plan import ActionPlan


# =====================================================================
# COMPOUND DETECTION
# =====================================================================


@dataclass(frozen=True)
class CompoundTaskSignal:
    """Diagnostic information about why a request was judged
    compound (or not)."""

    is_compound: bool
    step_count: int
    fully_level3_count: int
    executable_count: int
    requires_clarification: bool
    clarification_reason: Optional[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_compound": self.is_compound,
            "step_count": self.step_count,
            "fully_level3_count": self.fully_level3_count,
            "executable_count": self.executable_count,
            "requires_clarification": self.requires_clarification,
            "clarification_reason": self.clarification_reason,
            "reason": self.reason,
        }


class CompoundTaskDetector:
    """Deterministic detector for compound natural-language tasks.

    A request is "compound" when ObjectiveUnderstanding splits
    it into at least two independently executable Level-3 OS
    steps. This is intentionally a structural property of the
    understanding, not a lexical match on "and" / "then".

    The detector is read-only and side-effect free.
    """

    def __init__(
        self,
        objective_understanding: ObjectiveUnderstanding,
        min_steps: int = 2,
    ) -> None:
        if objective_understanding is None:
            raise ValueError(
                "CompoundTaskDetector requires an "
                "ObjectiveUnderstanding instance."
            )
        if min_steps < 2:
            raise ValueError(
                "CompoundTaskDetector min_steps must be >= 2."
            )
        self._ou = objective_understanding
        self._min_steps = min_steps

    def analyze(self, text: str) -> CompoundTaskSignal:
        if not text or not text.strip():
            return CompoundTaskSignal(
                is_compound=False,
                step_count=0,
                fully_level3_count=0,
                executable_count=0,
                requires_clarification=True,
                clarification_reason="Empty request.",
                reason="empty_input",
            )

        try:
            understanding = self._ou.understand(text)
        except Exception as exc:
            return CompoundTaskSignal(
                is_compound=False,
                step_count=0,
                fully_level3_count=0,
                executable_count=0,
                requires_clarification=True,
                clarification_reason=str(exc),
                reason="understanding_failed",
            )

        steps = understanding.steps
        fully_l3 = sum(1 for s in steps if s.is_level3)
        executable = sum(1 for s in steps if s.executable_intent)

        if not steps:
            return CompoundTaskSignal(
                is_compound=False,
                step_count=0,
                fully_level3_count=0,
                executable_count=0,
                requires_clarification=(
                    understanding.requires_clarification
                ),
                clarification_reason=(
                    understanding.clarification_reason
                ),
                reason="no_steps",
            )

        # A request is genuinely compound when ObjectiveUnderstanding
        # produced 2+ steps AND at least 2 of them are executable
        # Level 3 OS steps. Mixed-level (L3 + L1 conversation) is
        # NOT a compound OS task: it must still fall through to the
        # conversation pipeline.
        is_compound = (
            len(steps) >= self._min_steps
            and fully_l3 >= self._min_steps
            and executable >= self._min_steps
        )

        if is_compound:
            reason = "multi_step_level3"
        elif len(steps) >= self._min_steps and fully_l3 < self._min_steps:
            reason = "mixed_level_not_compound_os"
        elif executable < self._min_steps:
            reason = "insufficient_executable_steps"
        else:
            reason = "single_step"

        return CompoundTaskSignal(
            is_compound=is_compound,
            step_count=len(steps),
            fully_level3_count=fully_l3,
            executable_count=executable,
            requires_clarification=(
                understanding.requires_clarification
            ),
            clarification_reason=(
                understanding.clarification_reason
            ),
            reason=reason,
        )


# =====================================================================
# WORKFLOW PLAN BUILDER
# =====================================================================


def _full_supported_operations() -> frozenset:
    """Return the full set of supported operations.

    The single-step run_level3 path relies on the
    ActionExecutor's SUPPORTED_OPERATIONS set when it
    dispatches a plan. To stay architecturally consistent,
    the compound path must accept the same set of operations
    in its planning preflight.
    """
    try:
        from genesis_os.action_executor import ActionExecutor
        return frozenset(ActionExecutor.SUPPORTED_OPERATIONS)
    except Exception:
        return frozenset()


def build_workflow_plan_from_understanding(
    understanding: ObjectiveUnderstandingResult,
    *,
    workflow_id: str = "",
) -> Optional[WorkflowPlan]:
    """Build a validated WorkflowPlan from a compound
    ObjectiveUnderstandingResult.

    Returns None when the understanding is not a compound,
    fully-Level-3, executable plan. The caller must then fall
    back to the single-step path.

    The plan is built directly from each step's decision so
    the ActionPlans carry the exact intent, target and
    parameters produced by the WorkflowDecisionEngine. Each
    step depends on the previous one (sequential workflow).
    """

    if understanding is None or not understanding.steps:
        return None
    if not understanding.fully_level3:
        return None
    if understanding.requires_clarification:
        return None
    if len(understanding.steps) < 2:
        return None
    # All steps must be executable Level-3 intents.
    if not all(step.executable_intent for step in understanding.steps):
        return None

    workflow_steps: List[WorkflowStep] = []
    previous_id: Optional[str] = None

    for index, step_intent in enumerate(understanding.steps, start=1):
        decision = dict(step_intent.decision)
        # Ensure level/mode are explicit on the per-step decision.
        decision.setdefault("level", 3)
        decision.setdefault("mode", "os")
        decision.setdefault(
            "operation",
            step_intent.operation or decision.get("intent"),
        )
        decision.setdefault("task", step_intent.text)
        decision.setdefault("parameters", {})

        # ActionPlan.from_decision enforces the Level-3
        # contract (level/mode/operation). The full operation
        # allow-list (including non-application ops like
        # media.*, window.*, math.*, hardware.*, etc.) is
        # enforced by the ActionExecutor when the step
        # actually dispatches, so we deliberately do NOT call
        # action_plan.validate() here with the strict
        # APPLICATION_OPERATIONS default. The single-step
        # run_level3 path behaves the same way: it builds the
        # plan via ActionPlan.from_decision and lets the
        # executor validate with its full SUPPORTED_OPERATIONS.
        action_plan = ActionPlan.from_decision(decision)

        step_id = f"step-{index:02d}-{step_intent.step_id}"
        depends_on: tuple[str, ...] = (
            (previous_id,) if previous_id is not None else ()
        )

        workflow_steps.append(
            WorkflowStep(
                step_id=step_id,
                plan=action_plan,
                depends_on=depends_on,
                # Each step is independently verified.
                verification_required=True,
                max_retries=1,
                # Destructive steps are still gated by
                # ExecutionSafety inside ActionExecutor; do
                # not auto-retry them.
                retryable=False,
                metadata={
                    "objective_understanding_version": (
                        understanding.metadata.get("version", "")
                    ),
                    "step_text": step_intent.text,
                },
            )
        )
        previous_id = step_id

    plan = WorkflowPlan(
        objective=understanding.objective,
        steps=tuple(workflow_steps),
        workflow_id=workflow_id or f"compound-{id(understanding)}",
        version="3.17.0",
        metadata={
            "source": "compound_task_router",
            "overall_intent": understanding.overall_intent,
            "overall_risk": understanding.overall_risk,
        },
    )
    # Structural plan validation (step ids, dependencies, etc.).
    plan.validate()
    # Per-step plan validation uses the SAME operation set
    # the ActionExecutor will use at dispatch time, so the
    # compound path is symmetric with the single-step path.
    full_ops = _full_supported_operations()
    for step in plan.steps:
        step.validate()
        step.plan.validate(
            supported_operations=full_ops or None,
        )
    return plan


# =====================================================================
# COMPOUND TASK ROUTER
# =====================================================================


@dataclass(frozen=True)
class CompoundTaskOutcome:
    """Outcome of asking the router to handle a request.

    ``plan`` is non-None iff the request was judged compound
    AND a valid WorkflowPlan was produced. The caller then
    dispatches the plan through the existing
    UniversalDesktopWorkflowEngine.

    ``single_step_fallback`` is True when the request is not
    compound; the caller must keep using the existing
    single-step run_level3 path. ``signal`` is always set so
    the caller can log/display the diagnostic.
    """

    plan: Optional[WorkflowPlan]
    signal: CompoundTaskSignal
    single_step_fallback: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "single_step_fallback": self.single_step_fallback,
            "signal": self.signal.to_dict(),
            "plan": self.plan.to_dict() if self.plan is not None else None,
        }


class CompoundTaskRouter:
    """Top-level glue that asks the detector and (if compound)
    builds the WorkflowPlan.

    The router is a stateless orchestrator: callers reuse it
    for every request.
    """

    def __init__(
        self,
        objective_understanding: ObjectiveUnderstanding,
        workflow_decomposer: Optional[WorkflowDecomposer] = None,
    ) -> None:
        self._detector = CompoundTaskDetector(
            objective_understanding
        )
        # WorkflowDecomposer is the canonical planner used by
        # the Level 3.8 path. We keep it available but the
        # build_workflow_plan_from_understanding adapter is
        # preferred because it preserves per-step intents
        # verbatim.
        self._decomposer = workflow_decomposer or WorkflowDecomposer()

    def route(self, text: str) -> CompoundTaskOutcome:
        signal = self._detector.analyze(text)
        if not signal.is_compound:
            return CompoundTaskOutcome(
                plan=None,
                signal=signal,
                single_step_fallback=True,
            )

        understanding = self._detector._ou.understand(text)
        plan = build_workflow_plan_from_understanding(understanding)
        if plan is None:
            return CompoundTaskOutcome(
                plan=None,
                signal=signal,
                single_step_fallback=True,
            )

        return CompoundTaskOutcome(
            plan=plan,
            signal=signal,
            single_step_fallback=False,
        )
