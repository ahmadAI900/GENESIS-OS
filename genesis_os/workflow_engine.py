"""Genesis OS — Level 3.9 universal desktop workflow engine with observation loop, recovery, session state, and progress events.

Pipeline:
    validated plan → safety preflight → sequential execution
    → OBSERVE actual state → compare expected vs actual
    → RECOVER on failure (bounded strategies)
    → UPDATE session state
    → EMIT progress events
    → per-step evidence → state update → final verification/report

No operation bypasses ActionExecutor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from .action_executor import ActionExecutor
from .action_result import ActionResult
from .workflow_models import WorkflowPlan, WorkflowResult, WorkflowState
from .workflow_planner import WorkflowPlanner
from .capability_resolver import CapabilityResolver
from .workflow_capability import (
    WorkflowCapabilityResolver,
)
from .observation_loop import ObservationLoop
from .recovery_engine import RecoveryEngine, RecoveryReplanner
from .session_state import SessionState
from .progress_events import ProgressTracker, EventEmitter, EventType, EventSeverity


@dataclass
class CancellationToken:
    """Token for cooperative cancellation of long-running workflows."""
    cancelled: bool = False
    reason: Optional[str] = None

    def cancel(self, reason: str = "Cancelled by user") -> None:
        self.cancelled = True
        self.reason = reason

    def check(self) -> None:
        """Raise if cancellation was requested."""
        if self.cancelled:
            raise WorkflowCancelledError(self.reason or "Workflow cancelled")


class WorkflowCancelledError(RuntimeError):
    """Raised when a workflow is cancelled."""
    pass

class UniversalDesktopWorkflowEngine:
    VERSION = "3.9.0"

    def __init__(
        self,
        action_executor: ActionExecutor,
        planner: Optional[WorkflowPlanner] = None,
        capability_resolver: Optional[CapabilityResolver] = None,
        os_manager=None,
        enable_recovery: bool = True,
        event_emitter: Optional[EventEmitter] = None,
    ):
        if action_executor is None:
            raise ValueError(
                "UniversalDesktopWorkflowEngine requires an ActionExecutor."
            )
        self.executor = action_executor
        self.planner = planner or WorkflowPlanner()
        self._capability_resolver = (
            capability_resolver or CapabilityResolver()
        )
        self._workflow_capability_resolver = (
            WorkflowCapabilityResolver(
                self._capability_resolver
            )
        )
        # Observation loop for closed-loop verification
        self._observation_loop = ObservationLoop(os_manager) if os_manager else None
        # Recovery engine for bounded self-recovery
        self._recovery_engine = RecoveryEngine(os_manager) if os_manager and enable_recovery else None
        self._recovery_replanner = RecoveryReplanner(self._recovery_engine) if self._recovery_engine else None
        # Session state for context-aware execution
        self._session_state = SessionState(os_manager) if os_manager else None
        # OSManager reference for compound GUI focus (optional)
        self._os_manager = os_manager
        # Progress tracking
        self._event_emitter = event_emitter or EventEmitter()
        self._progress_tracker = ProgressTracker(self._event_emitter)

    def validate(self, workflow: WorkflowPlan) -> None:
        from genesis_os.contracts import Workflow as WorkflowContract
        # Phase 1 contract first: malformed shapes rejected before
        # planner validation runs.
        WorkflowContract.from_workflow_plan(workflow)
        self.planner.validate(workflow)

    def execute(
        self,
        workflow: WorkflowPlan,
        *,
        context: Optional[dict] = None,
        replanner: Optional[Callable[[WorkflowPlan, WorkflowState], Optional[WorkflowPlan]]] = None,
        max_replans: int = 0,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> WorkflowResult:
        """Execute a workflow plan with progress tracking and cancellation support."""
        cancellation_token = cancellation_token or CancellationToken()
        
        try:
            self.validate(workflow)
        except Exception as exc:
            return WorkflowResult(
                success=False,
                status="invalid_plan",
                objective=getattr(workflow, "objective", ""),
                steps=(),
                state={},
                final_verified=False,
                message="Genesis could not safely validate the desktop workflow.",
                error=str(exc),
            )

        if max_replans < 0:
            raise ValueError("max_replans cannot be negative.")

        task_id = workflow.workflow_id or f"task-{id(workflow)}"
        total_steps = len(workflow.steps)
        
        # Initialize progress tracking
        self._progress_tracker.start_task(task_id, workflow.objective, total_steps)
        self._progress_tracker.planning()
        self._progress_tracker.plan_created(total_steps)

        state = WorkflowState(
            objective=workflow.objective,
            context=dict(context or {}),
            status="running",
        )
        results = []

        # Initialize session state task tracking
        if self._session_state:
            step_infos = [
                {
                    "step_id": s.step_id,
                    "operation": s.plan.operation,
                    "target": s.plan.target,
                }
                for s in workflow.steps
            ]
            self._session_state.start_task(
                task_id=task_id,
                objective=workflow.objective,
                steps=step_infos,
            )

        current_workflow = workflow
        while True:
            # Check for cancellation at workflow level
            try:
                cancellation_token.check()
            except WorkflowCancelledError as exc:
                self._progress_tracker.cancel_task()
                if self._session_state:
                    self._session_state.complete_task(success=False)
                return WorkflowResult(
                    success=False,
                    status="cancelled",
                    objective=current_workflow.objective,
                    steps=tuple(results),
                    state=state.to_dict(),
                    final_verified=False,
                    message="Workflow was cancelled.",
                    error=str(exc),
                )

            restart = False

            for step_index, step in enumerate(current_workflow.steps):
                state.current_step = step.step_id

                # Check for cancellation at step level
                try:
                    cancellation_token.check()
                except WorkflowCancelledError as exc:
                    self._progress_tracker.cancel_task()
                    if self._session_state:
                        self._session_state.complete_task(success=False)
                    return WorkflowResult(
                        success=False,
                        status="cancelled",
                        objective=current_workflow.objective,
                        steps=tuple(results),
                        state=state.to_dict(),
                        final_verified=False,
                        message="Workflow was cancelled.",
                        error=str(exc),
                    )

                if any(dep not in state.completed_steps for dep in step.depends_on):
                    self._progress_tracker.waiting_for_dependency(
                        ", ".join(dep for dep in step.depends_on if dep not in state.completed_steps)
                    )
                    return self._failure(
                        current_workflow,
                        state,
                        results,
                        step.step_id,
                        "blocked",
                        "A required workflow dependency was not completed.",
                    )

                # Emit step started event
                step_desc = f"{step.plan.operation} on {step.plan.target or step.plan.application or 'target'}"
                self._progress_tracker.start_step(step.step_id, step_index + 1, step_desc)

                attempts = 0
                while True:
                    # Check for cancellation during retries
                    try:
                        cancellation_token.check()
                    except WorkflowCancelledError as exc:
                        self._progress_tracker.cancel_task()
                        if self._session_state:
                            self._session_state.complete_task(success=False)
                        return WorkflowResult(
                            success=False,
                            status="cancelled",
                            objective=current_workflow.objective,
                            steps=tuple(results),
                            state=state.to_dict(),
                            final_verified=False,
                            message="Workflow was cancelled.",
                            error=str(exc),
                        )

                    # Emit OS action invoked event
                    self._progress_tracker.invoke_os_action(step.plan.operation, step.plan.target or step.plan.application or "target")

                    # --- COMPOUND GUI PRE-FOCUS ---
                    # If this step is a targetless GUI interaction
                    # and the immediately preceding successfully-
                    # completed step was an ``application.open``,
                    # focus that app's window BEFORE dispatching
                    # the GUI call. Otherwise keystrokes would
                    # land in whatever window already had OS
                    # focus (typically the terminal that
                    # launched Genesis), not the just-opened app.
                    pre_focus_result: Optional[Dict[str, Any]] = None
                    pre_focus_app: Optional[str] = None
                    if self._needs_pre_focus(
                        step.plan.operation,
                        step.plan.target,
                    ):
                        preceding_app = self._preceding_app_target(
                            current_workflow.steps,
                            step_index,
                            completed_step_ids=(
                                state.completed_steps
                            ),
                        )
                        if preceding_app:
                            pre_focus_app = preceding_app
                            pre_focus_result = (
                                self._execute_focus_window(
                                    preceding_app
                                )
                            )

                            if not pre_focus_result.get(
                                "success"
                            ):
                                # Fail the step honestly: the
                                # window never appeared within
                                # the polling timeout. Do NOT
                                # proceed to dispatch a blind
                                # type_text call that would type
                                # into the wrong window.
                                result = ActionResult(
                                    success=False,
                                    operation=step.plan.operation,
                                    target=step.plan.target,
                                    application=(
                                        step.plan.application
                                    ),
                                    status="execution_failed",
                                    message=(
                                        f"Genesis could not focus "
                                        f"the window for "
                                        f"'{preceding_app}' "
                                        f"before "
                                        f"{step.plan.operation}."
                                    ),
                                    executed=False,
                                    verified=False,
                                    plan=step.plan.to_dict(),
                                    error=(
                                        pre_focus_result.get(
                                            "error"
                                        )
                                        or (
                                            "Window not found "
                                            "within timeout."
                                        )
                                    ),
                                    execution={
                                        "pre_focus": (
                                            pre_focus_result
                                        ),
                                    },
                                )
                                result_dict = result.to_dict()
                                result_dict["pre_focus"] = (
                                    pre_focus_result
                                )
                                attempts += 1
                                state.record(
                                    step.step_id,
                                    {
                                        "attempt": attempts,
                                        **result_dict,
                                    },
                                )
                                self._progress_tracker.fail_step(
                                    step.step_id,
                                    step_index + 1,
                                    result.error
                                    or "Window not found within timeout.",
                                )
                                if self._session_state:
                                    self._session_state.update_task_step(
                                        step.step_id,
                                        success=False,
                                    )
                                state.failed_step = step.step_id
                                step_record = {
                                    "step_id": step.step_id,
                                    "attempt": attempts,
                                    "operation": step.plan.operation,
                                    "target": step.plan.target,
                                    "application": step.plan.application,
                                    "status": result.status,
                                    "success": result.success,
                                    "trustworthy_success": False,
                                    "executed": result.executed,
                                    "verified": result.verified,
                                    "evidence": result.verification,
                                    "execution": result.execution,
                                    "error": result.error,
                                    "observation": None,
                                    "pre_focus": pre_focus_result,
                                    "pre_focus_app": pre_focus_app,
                                }
                                results.append(step_record)
                                return self._failure(
                                    current_workflow,
                                    state,
                                    results,
                                    step.step_id,
                                    "execution_failed",
                                    result.message,
                                    result.error,
                                )

                            # Stash the focus pattern in the plan parameters so the
                            # executor's dispatch passes it
                            # through to ``gui.type_text`` /
                            # ``gui.paste_text``. The provider
                            # will call ``focus_window`` again
                            # (idempotent — the window is
                            # already focused, so it returns
                            # immediately on the first poll).
                            # For ``gui.click`` and other ops
                            # without an executor-side focus
                            # path, this metadata is purely
                            # informational.
                            step.plan.parameters.setdefault(
                                "focus_title_pattern",
                                preceding_app,
                            )

                    result = self.executor.execute(step.plan)
                    if pre_focus_result is not None:
                        result_dict = result.to_dict()
                        result_dict["pre_focus"] = pre_focus_result
                        if pre_focus_app:
                            result_dict["pre_focus_app"] = (
                                pre_focus_app
                            )
                    else:
                        result_dict = result.to_dict()
                    attempts += 1
                    state.record(step.step_id, {
                        "attempt": attempts,
                        **result_dict,
                    })

                    # Emit observation event
                    if self._observation_loop and result.success:
                        self._progress_tracker.observing()

                    # --- OBSERVATION LOOP: observe actual state after execution ---
                    observation_result = None
                    if self._observation_loop and result.success:
                        try:
                            observation = self._observation_loop.observe(
                                step.step_id, step.plan, result
                            )
                            observation_result = observation.to_dict()
                            result_dict["observation"] = observation_result
                            
                            # Emit verifying event
                            self._progress_tracker.verifying()
                            
                            # If observation doesn't match expected, treat as verification failure
                            if not observation.matches_expected:
                                result_dict["verification_failed_by_observation"] = True
                                result_dict["observation_discrepancy"] = observation.discrepancy
                                # Force verification to fail
                                result = ActionResult(
                                    success=result.success,
                                    operation=result.operation,
                                    target=result.target,
                                    application=result.application,
                                    status="verification_failed",
                                    message=observation.discrepancy or "Observation did not match expected state",
                                    executed=result.executed,
                                    verified=False,
                                    already_in_desired_state=result.already_in_desired_state,
                                    retry_count=result.retry_count,
                                    error=observation.discrepancy,
                                    execution=result.execution,
                                    verification=result.verification,
                                    plan=result.plan,
                                    metadata=result.metadata,
                                )
                                result_dict = result.to_dict()
                                result_dict["observation"] = observation_result
                        except Exception as exc:
                            result = ActionResult(
                                success=result.success,
                                operation=result.operation,
                                target=result.target,
                                application=result.application,
                                status="verification_failed",
                                message=str(exc),
                                executed=result.executed,
                                verified=False,
                                already_in_desired_state=False,
                                retry_count=result.retry_count,
                                error=str(exc),
                                execution=result.execution,
                                verification=result.verification,
                                plan=result.plan,
                                metadata=result.metadata,
                            )
                            result_dict = result.to_dict()
                            result_dict["observation_error"] = str(exc)

                    step_record = {
                        "step_id": step.step_id,
                        "attempt": attempts,
                        "operation": step.plan.operation,
                        "target": step.plan.target,
                        "application": step.plan.application,
                        "status": result.status,
                        "success": result.success,
                        "trustworthy_success": result.trustworthy_success,
                        "executed": result.executed,
                        "verified": result.verified,
                        "evidence": result.verification,
                        "execution": result.execution,
                        "error": result.error,
                        "observation": observation_result,
                        "pre_focus": pre_focus_result,
                        "pre_focus_app": pre_focus_app,
                    }
                    results.append(step_record)

                    if result.status == "confirmation_required":
                        self._progress_tracker.confirmation_required(
                            f"Step {step_index + 1}/{total_steps}: {step.plan.operation} on {step.plan.target or step.plan.application}"
                        )
                        return self._failure(
                            current_workflow, state, results,
                            step.step_id, "confirmation_required",
                            result.user_message(), result.error,
                        )

                    if result.success and (result.verified or not step.verification_required):
                        self._progress_tracker.complete_os_action(step.plan.operation, step.plan.target or step.plan.application or "target")
                        self._progress_tracker.complete_step(step.step_id, step_index + 1, step_desc)
                        state.completed_steps.append(step.step_id)
                        state.context[f"step:{step.step_id}"] = result_dict

                        # --- PHASE 1 CHECKPOINT GATE ---
                        # Every completed step produces a
                        # contract-validated checkpoint record.
                        # In-memory only: durable resume across
                        # restarts is Phase 16. Malformed ids or
                        # incoherent states raise loudly here
                        # instead of recording garbage.
                        try:
                            from genesis_os.contracts import (
                                Checkpoint as CheckpointContract,
                            )
                            try:
                                from genesis_os.capability_provider_registry import (
                                    NON_IDEMPOTENT_CAPABILITIES,
                                )
                                _step_idem = (
                                    step.plan.operation
                                    not in NON_IDEMPOTENT_CAPABILITIES
                                )
                            except Exception:
                                _step_idem = True
                            _checkpoint = CheckpointContract.from_step_completion(
                                workflow_id=task_id,
                                step_id=str(step.step_id or ""),
                                operation=str(step.plan.operation or ""),
                                success=bool(result.success),
                                verified=bool(result.verified),
                                executed=bool(result.executed),
                                is_idempotent=_step_idem,
                                evidence=dict(result.verification or {}),
                                error=result.error,
                            )
                            state.context[f"checkpoint:{step.step_id}"] = (
                                _checkpoint.to_dict()
                            )
                        except Exception as _cp_exc:
                            from genesis_os.contracts import (
                                ContractViolationError,
                            )
                            raise ContractViolationError(
                                "step completion failed Checkpoint "
                                f"contract: {_cp_exc}"
                            ) from _cp_exc

                        # --- UPDATE SESSION STATE ---
                        if self._session_state:
                            self._session_state.update_task_step(step.step_id, success=True)
                            self._update_session_state_from_result(step.plan, result)
                        break

                    # ``requires_runtime_resolution`` is an explicit,
                    # non-verified handoff from the executor (used for
                    # anaphoric file/document references that the runtime
                    # entity binder must resolve). It is NEVER a success
                    # shortcut. Carving it into ``completed`` here used to
                    # be the production-critical Phase 0 bug for
                    # ``gui.type_text`` / ``gui.paste_text`` / ``gui.focus_window``
                    # — the executor was returning it without ever calling
                    # ``pyautogui.typewrite`` and the workflow engine was
                    # promoting it to ``verified=True``. The executor now
                    # performs the closed-loop dispatch itself for GUI
                    # text input, so this branch only fires for genuine
                    # anaphoric L3 plans and must surface as a real
                    # unresolved failure.

                    # Handle retry
                    retryable = (
                        step.retryable
                        and attempts <= step.max_retries
                        and result.status in {"execution_failed", "verification_failed"}
                    )
                    if retryable:
                        self._progress_tracker.retry_step(step.step_id, step_index + 1, attempts, step.max_retries)
                        continue

                    state.failed_step = step.step_id
                    failure_status = result.status or "step_failed"

                    # Update session state for failed step
                    if self._session_state:
                        self._session_state.update_task_step(step.step_id, success=False)

                    self._progress_tracker.fail_step(step.step_id, step_index + 1, result.error or result.message or "Unknown error")

                    # Replanning is explicit and bounded. It never happens
                    # implicitly after an arbitrary failure.
                    # First try the provided replanner callback
                    replan_candidate = None
                    if (
                        replanner is not None
                        and state.replans < max_replans
                        and failure_status in {
                            "verification_failed",
                            "execution_failed",
                            "failed",
                        }
                    ):
                        self._progress_tracker.replanning()
                        replan_candidate = replanner(current_workflow, state)

                    # If no external replanner or it returned None, try built-in recovery
                    if replan_candidate is None and self._recovery_replanner:
                        self._progress_tracker.recovering("built-in recovery")
                        replan_candidate = self._recovery_replanner.replan_on_failure(
                            failed_step_id=step.step_id,
                            workflow=current_workflow,
                            state=state,
                            execution_result=result,
                        )

                    if replan_candidate is not None:
                        self.validate(replan_candidate)
                        state.replans += 1
                        current_workflow = replan_candidate
                        restart = True
                        break

                    return self._failure(
                        current_workflow, state, results,
                        step.step_id, failure_status,
                        result.user_message(), result.error,
                    )

                if restart:
                    break

            if restart:
                continue
            break

        state.current_step = None
        state.status = "completed"
        state.failed_step = None

        # Final verification is intentionally derived from every required
        # step, not merely from the executor's return code.
        latest_by_step = {}
        for item in results:
            latest_by_step[item["step_id"]] = item

        # A step is considered verified ONLY when the executor
        # reported success and verification on a real observation.
        # The previous carve-out that accepted
        # ``requires_runtime_resolution`` for gui.* operations as
        # verified was the Phase 0 production-critical bug: the
        # executor returned that status without dispatching
        # ``pyautogui.typewrite``, so the workflow engine was
        # reporting ``1 verified step(s)`` for work it never
        # performed. The executor now performs the closed-loop
        # dispatch itself for GUI text input (resolve focused
        # window, refuse unsafe targets, dispatch, verify focus
        # retained), so the only ``verified=True`` path is a
        # real post-state observation. Anything else stays
        # ``verified=False`` and the workflow is reported as
        # ``verification_failed`` instead of ``completed``.
        def _step_verified(step_record: Dict[str, Any]) -> bool:
            if step_record.get("trustworthy_success"):
                return True
            return False

        final_verified = bool(
            current_workflow.steps
            and len(state.completed_steps) == len(current_workflow.steps)
            and all(
                _step_verified(latest_by_step[step.step_id])
                for step in current_workflow.steps
                if step.step_id in latest_by_step
            )
        )

        # Complete session state task
        if self._session_state:
            self._session_state.complete_task(success=final_verified)

        if not final_verified:
            state.status = "verification_failed"
            self._progress_tracker.fail_task("Final workflow verification did not pass.")
            return WorkflowResult(
                success=False,
                status="verification_failed",
                objective=current_workflow.objective,
                steps=tuple(results),
                state=state.to_dict(),
                final_verified=False,
                message="Genesis completed execution steps but could not verify the final workflow state.",
                error="Final workflow verification did not pass.",
            )

        self._progress_tracker.complete_task()
        return WorkflowResult(
            success=True,
            status="completed",
            objective=current_workflow.objective,
            steps=tuple(results),
            state=state.to_dict(),
            final_verified=True,
            message=(
                f"Genesis completed the objective in "
                f"{len(current_workflow.steps)} verified step(s)."
            ),
        )

    def _update_session_state_from_result(self, plan: ActionPlan, result: ActionResult) -> None:
        """Update session state based on successful action result."""
        if not self._session_state:
            return

        op = plan.operation
        target = plan.target

        try:
            # Application state
            if op == "application.open":
                app_name = plan.application or target
                if app_name:
                    self._session_state.update_application(
                        app_name,
                        is_focused=True,
                        metadata={"opened_by_genesis": True},
                    )
            elif op == "application.close":
                app_name = plan.application or target
                if app_name:
                    self._session_state.mark_application_closed(app_name)
            elif op == "application.inspect":
                app_name = plan.application or target
                if app_name:
                    # The observation loop already refreshes state
                    pass

            # Filesystem state
            elif op == "folder.open":
                if target:
                    self._session_state.set_current_folder(target)
            elif op == "file.open" or op == "file.read":
                if target:
                    self._session_state.set_active_document(target)
            elif op == "file.create":
                if target:
                    self._session_state.add_recent_file(target)
                    self._session_state.set_active_document(target)
            elif op in ("file.move", "file.copy"):
                dest = plan.parameters.get("destination")
                if dest:
                    self._session_state.add_recent_file(dest)
                    self._session_state.set_active_document(dest)

            # Browser state
            elif op == "browser.open_url":
                if target:
                    self._session_state.update_browser(
                        "default",
                        url=target,
                    )
            elif op == "browser.search":
                self._session_state.update_browser(
                    plan.parameters.get("engine", "google"),
                    search_query=plan.parameters.get("query", target),
                    search_engine=plan.parameters.get("engine", "google"),
                )

            # Clipboard
            elif op == "clipboard.copy":
                text = plan.parameters.get("text", target)
                if text:
                    self._session_state.set_clipboard(text)

        except Exception:
            pass  # Silent failure for session state updates

    # --------------------------------------------------------
    # COMPOUND GUI FOCUS RESOLUTION
    # --------------------------------------------------------
    #
    # When a compound plan is "open <app> and type <text>", the
    # second step's ``target`` is None because the user did not
    # name a window. The previous step ``application.open`` did
    # name the app though. Without an explicit focus_window call
    # between them, ``gui.type_text`` would dispatch keystrokes
    # into whichever window already had OS focus (typically the
    # terminal that launched Genesis itself) instead of the
    # just-opened app.
    #
    # These helpers detect that compound shape and inject a
    # ``focus_window(<app>)`` call before the GUI step executes.
    # If the window is not found within a short polling window
    # the step fails honestly instead of typing blindly.

    _GUI_TARGETLESS_OPS = frozenset({
        "gui.type_text",
        "gui.paste_text",
        "gui.click",
        "gui.double_click",
        "gui.scroll",
        "gui.select",
        "gui.read_visible_text",
        "gui.keyboard_action",
    })

    _FOCUS_TIMEOUT_SECONDS = 3.0
    _FOCUS_POLL_INTERVAL_SECONDS = 0.2

    @classmethod
    def _preceding_app_target(
        cls,
        steps: Sequence["WorkflowStep"],
        current_index: int,
        *,
        completed_step_ids: Optional[Sequence[str]] = None,
    ) -> Optional[str]:
        """Return the most-recently completed ``application.open``
        step's resolved app name that precedes ``current_index``.

        Used to anchor a targetless GUI step (``gui.type_text`` with
        ``target=None``) to the window of the app we just opened.
        Only steps whose ``step_id`` is in ``completed_step_ids``
        are considered, so we never anchor to an application.open
        that failed.
        """
        completed = set(completed_step_ids or ())
        for idx in range(current_index - 1, -1, -1):
            step = steps[idx]
            if completed and step.step_id not in completed:
                continue
            if step.plan.operation == "application.open":
                name = step.plan.application or step.plan.target
                if isinstance(name, str) and name.strip():
                    return name
                return None
        return None

    @classmethod
    def _needs_pre_focus(
        cls,
        operation: str,
        target: Optional[str],
    ) -> bool:
        """A targetless GUI step that benefits from a pre-focus."""
        if not isinstance(operation, str):
            return False
        if operation not in cls._GUI_TARGETLESS_OPS:
            return False
        if target is not None and str(target).strip():
            return False
        return True

    def _execute_focus_window(
        self,
        title_pattern: str,
    ) -> Dict[str, Any]:
        """Invoke ``focus_window`` through the OSManager GUI bridge.

        Returns a dict shaped like a GUI action result so the
        workflow engine can fold it into the step record without
        depending on ``ActionResult``.
        """
        if self._os_manager is None:
            return {
                "success": False,
                "operation": "gui.focus_window",
                "error": (
                    "OSManager is not available; cannot focus "
                    "window before typing."
                ),
                "verified": False,
            }
        try:
            raw = self._os_manager.gui_action(
                "focus_window",
                title_pattern=title_pattern,
                timeout=self._FOCUS_TIMEOUT_SECONDS,
                poll_interval=self._FOCUS_POLL_INTERVAL_SECONDS,
            )
        except Exception as exc:
            return {
                "success": False,
                "operation": "gui.focus_window",
                "error": str(exc),
                "verified": False,
            }

        if not isinstance(raw, dict):
            raw = {"success": False, "error": "GUI focus returned non-dict."}
        raw.setdefault("operation", "gui.focus_window")
        raw.setdefault("verified", bool(raw.get("success")))
        return raw

    @staticmethod
    def _failure(workflow, state, results, step_id, status, message, error=None):
        state.status = status
        state.failed_step = step_id
        return WorkflowResult(
            success=False,
            status=status,
            objective=workflow.objective,
            steps=tuple(results),
            state=state.to_dict(),
            final_verified=False,
            message=message,
            error=error,
        )
