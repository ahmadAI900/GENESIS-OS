"""
Genesis OS — Level 3 Recovery Engine.

Bounded self-recovery strategies for common failure modes:

    launch method A fails → try method B
    file path not found → search canonical locations
    window not found → inspect running applications
    operation failed → re-observe state
    unexpected application state → replan affected branch

Every recovery attempt is bounded:
    max retries
    time limits
    failure state
    recovery policy
    final explanation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .action_plan import ActionPlan
from .action_result import ActionResult
from .os_manager import OSManager
from .workflow_models import WorkflowPlan, WorkflowState


@dataclass(frozen=True)
class RecoveryStrategy:
    """A named recovery strategy with bounded attempts."""
    name: str
    description: str
    max_attempts: int = 3
    timeout_seconds: float = 30.0
    applicable_errors: Tuple[str, ...] = ()
    applicable_operations: Tuple[str, ...] = ()


@dataclass
class RecoveryAttempt:
    """Record of a single recovery attempt."""
    strategy_name: str
    attempt_number: int
    success: bool
    error: Optional[str] = None
    modified_plan: Optional[ActionPlan] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryResult:
    """Result of attempting recovery for a failed step."""
    original_step_id: str
    original_error: str
    strategies_attempted: List[RecoveryAttempt]
    recovered: bool
    final_plan: Optional[ActionPlan] = None
    final_error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_step_id": self.original_step_id,
            "original_error": self.original_error,
            "strategies_attempted": [
                {
                    "strategy_name": a.strategy_name,
                    "attempt_number": a.attempt_number,
                    "success": a.success,
                    "error": a.error,
                    "metadata": a.metadata,
                }
                for a in self.strategies_attempted
            ],
            "recovered": self.recovered,
            "final_plan": self.final_plan.to_dict() if self.final_plan else None,
            "final_error": self.final_error,
            "metadata": self.metadata,
        }


class RecoveryEngine:
    """
    Bounded self-recovery engine for workflow execution failures.
    
    Provides configurable recovery strategies for common failure modes.
    Each strategy has bounded attempts and clear failure conditions.
    """

    VERSION = "3.0.0"

    def __init__(self, os_manager: OSManager):
        if os_manager is None:
            raise ValueError("RecoveryEngine requires an OSManager.")
        self.os_manager = os_manager
        self._strategies: Dict[str, RecoveryStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self) -> None:
        """Register built-in recovery strategies."""
        self.register_strategy(RecoveryStrategy(
            name="application_launch_fallback",
            description="Try alternative application launch methods",
            max_attempts=2,
            applicable_errors=("application_not_found", "launch_failed", "execution_failed"),
            applicable_operations=("application.open",),
        ))
        self.register_strategy(RecoveryStrategy(
            name="file_path_fallback",
            description="Search canonical locations for missing files",
            max_attempts=3,
            applicable_errors=("file_not_found", "path_not_found", "missing_target"),
            applicable_operations=("file.open", "file.read", "file.inspect", "file.delete", "file.move", "file.copy"),
        ))
        self.register_strategy(RecoveryStrategy(
            name="folder_path_fallback",
            description="Search canonical locations for missing folders",
            max_attempts=3,
            applicable_errors=("folder_not_found", "path_not_found", "missing_target"),
            applicable_operations=("folder.open", "folder.inspect", "folder.create", "folder.organize"),
        ))
        self.register_strategy(RecoveryStrategy(
            name="window_focus_fallback",
            description="Find and focus application window via process inspection",
            max_attempts=2,
            applicable_errors=("window_not_found", "focus_failed"),
            applicable_operations=("application.open", "application.inspect"),
        ))
        self.register_strategy(RecoveryStrategy(
            name="state_reobservation",
            description="Re-observe system state after unexpected result",
            max_attempts=2,
            applicable_errors=("verification_failed", "state_mismatch", "unexpected_state"),
            applicable_operations=("application.open", "application.close", "file.create", "file.delete", "file.move", "folder.create", "folder.delete"),
        ))
        self.register_strategy(RecoveryStrategy(
            name="alternative_application",
            description="Try alternative application for the same task",
            max_attempts=2,
            applicable_errors=("application_not_found", "unsupported_application"),
            applicable_operations=("application.open",),
        ))

    def register_strategy(self, strategy: RecoveryStrategy) -> None:
        """Register a recovery strategy."""
        self._strategies[strategy.name] = strategy

    def get_strategy(self, name: str) -> Optional[RecoveryStrategy]:
        """Get a strategy by name."""
        return self._strategies.get(name)

    def list_strategies(self) -> List[RecoveryStrategy]:
        """List all registered strategies."""
        return list(self._strategies.values())

    def find_applicable_strategies(
        self,
        operation: str,
        error: str,
    ) -> List[RecoveryStrategy]:
        """Find strategies applicable to the given operation and error."""
        applicable = []
        for strategy in self._strategies.values():
            if operation in strategy.applicable_operations or not strategy.applicable_operations:
                if not strategy.applicable_errors or any(e in error.lower() for e in strategy.applicable_errors):
                    applicable.append(strategy)
        return applicable

    def attempt_recovery(
        self,
        step_id: str,
        plan: ActionPlan,
        error: str,
        execution_result: ActionResult,
        workflow_state: WorkflowState,
    ) -> RecoveryResult:
        """
        Attempt to recover from a failed step execution.
        
        Tries applicable strategies in order until one succeeds or all are exhausted.
        """
        strategies = self.find_applicable_strategies(plan.operation, error)
        attempts = []
        recovered = False
        final_plan = None
        final_error = error

        for strategy in strategies:
            for attempt_num in range(1, strategy.max_attempts + 1):
                attempt = self._execute_strategy(
                    strategy, attempt_num, plan, error, execution_result, workflow_state
                )
                attempts.append(attempt)

                if attempt.success:
                    recovered = True
                    final_plan = attempt.modified_plan
                    final_error = None
                    break

            if recovered:
                break

        from genesis_os.contracts import Recovery as RecoveryContract

        outcome = RecoveryResult(
            original_step_id=step_id,
            original_error=error,
            strategies_attempted=attempts,
            recovered=recovered,
            final_plan=final_plan,
            final_error=final_error,
            metadata={
                "recovery_version": self.VERSION,
                "strategies_considered": [s.name for s in strategies],
            },
        )
        # Phase 1 contract: malformed recovery outcomes (e.g.
        # recovered=True with no final plan) are rejected here.
        RecoveryContract.from_recovery_result(outcome)
        return outcome

    def _execute_strategy(
        self,
        strategy: RecoveryStrategy,
        attempt_num: int,
        plan: ActionPlan,
        error: str,
        execution_result: ActionResult,
        workflow_state: WorkflowState,
    ) -> RecoveryAttempt:
        """Execute a single recovery strategy attempt."""
        try:
            if strategy.name == "application_launch_fallback":
                modified = self._try_alt_launch(plan)
            elif strategy.name == "file_path_fallback":
                modified = self._try_alt_file_path(plan)
            elif strategy.name == "folder_path_fallback":
                modified = self._try_alt_folder_path(plan)
            elif strategy.name == "window_focus_fallback":
                modified = self._try_window_focus(plan)
            elif strategy.name == "state_reobservation":
                modified = self._try_state_reobservation(plan, execution_result)
            elif strategy.name == "alternative_application":
                modified = self._try_alternative_app(plan)
            else:
                return RecoveryAttempt(
                    strategy_name=strategy.name,
                    attempt_number=attempt_num,
                    success=False,
                    error=f"Unknown strategy: {strategy.name}",
                )

            if modified is not None:
                # Validate the modified plan
                try:
                    modified.validate()
                    return RecoveryAttempt(
                        strategy_name=strategy.name,
                        attempt_number=attempt_num,
                        success=True,
                        modified_plan=modified,
                        metadata={"recovered_operation": modified.operation, "recovered_target": modified.target},
                    )
                except Exception as exc:
                    return RecoveryAttempt(
                        strategy_name=strategy.name,
                        attempt_number=attempt_num,
                        success=False,
                        error=f"Modified plan validation failed: {exc}",
                    )

            return RecoveryAttempt(
                strategy_name=strategy.name,
                attempt_number=attempt_num,
                success=False,
                error="Strategy did not produce a modified plan",
            )

        except Exception as exc:
            return RecoveryAttempt(
                strategy_name=strategy.name,
                attempt_number=attempt_num,
                success=False,
                error=f"Strategy execution failed: {exc}",
            )

    # --- Individual Recovery Strategies ---

    def _try_alt_launch(self, plan: ActionPlan) -> Optional[ActionPlan]:
        """Try alternative application launch methods."""
        app_name = plan.target or plan.application
        if not app_name:
            return None

        # The OSManager already has multiple launch methods internally
        # This strategy signals to the executor to try alternative paths
        # by adding a parameter hint
        return ActionPlan(
            operation=plan.operation,
            target=app_name,
            application=app_name,
            confidence=plan.confidence,
            parameters={**plan.parameters, "try_alt_launch": True, "recovery_attempt": True},
            reason=f"Recovery: retrying {app_name} with alternative launch method",
            source="RecoveryEngine:application_launch_fallback",
        )

    def _try_alt_file_path(self, plan: ActionPlan) -> Optional[ActionPlan]:
        """Search canonical locations for missing files."""
        from pathlib import Path
        target = plan.target
        if not target:
            return None

        # Search common locations
        search_roots = [
            Path.home() / "Documents",
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path.home() / "Pictures",
            Path.home() / "Videos",
            Path.home() / "Music",
            Path.cwd(),
        ]

        target_name = Path(target).name
        for root in search_roots:
            try:
                for match in root.rglob(target_name):
                    if match.is_file():
                        return ActionPlan(
                            operation=plan.operation,
                            target=str(match),
                            application=plan.application,
                            confidence=0.85,  # Lower confidence for recovered path
                            parameters={**plan.parameters, "recovered_path": True, "original_target": target},
                            reason=f"Recovery: found {target_name} at {match}",
                            source="RecoveryEngine:file_path_fallback",
                        )
            except Exception:
                continue

        return None

    def _try_alt_folder_path(self, plan: ActionPlan) -> Optional[ActionPlan]:
        """Search canonical locations for missing folders."""
        from pathlib import Path
        target = plan.target
        if not target:
            return None

        target_lower = target.lower().strip()
        standard_folders = {
            "downloads": Path.home() / "Downloads",
            "download": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "document": Path.home() / "Documents",
            "desktop": Path.home() / "Desktop",
            "pictures": Path.home() / "Pictures",
            "photos": Path.home() / "Pictures",
            "music": Path.home() / "Music",
            "videos": Path.home() / "Videos",
            "video": Path.home() / "Videos",
        }

        for name, path in standard_folders.items():
            if target_lower in (name, f"my {name}", f"{name} folder", f"my {name} folder"):
                if path.exists():
                    return ActionPlan(
                        operation=plan.operation,
                        target=str(path),
                        application=plan.application,
                        confidence=0.95,
                        parameters={**plan.parameters, "recovered_path": True, "original_target": target},
                        reason=f"Recovery: resolved {target} to {path}",
                        source="RecoveryEngine:folder_path_fallback",
                    )

        return None

    def _try_window_focus(self, plan: ActionPlan) -> Optional[ActionPlan]:
        """Find and focus application window via process inspection."""
        app_name = plan.target or plan.application
        if not app_name:
            return None

        try:
            result = self.os_manager.inspect_application(app_name)
            if result.get("running") and result.get("process_id"):
                return ActionPlan(
                    operation=plan.operation,
                    target=app_name,
                    application=app_name,
                    confidence=0.9,
                    parameters={**plan.parameters, "focus_existing": True, "process_id": result.get("process_id")},
                    reason=f"Recovery: {app_name} already running (PID {result.get('process_id')}), focusing",
                    source="RecoveryEngine:window_focus_fallback",
                )
        except Exception:
            pass

        return None

    def _try_state_reobservation(
        self,
        plan: ActionPlan,
        execution_result: ActionResult,
    ) -> Optional[ActionPlan]:
        """Re-observe system state after unexpected result."""
        # Check if the operation actually succeeded despite verification failure
        op = plan.operation

        try:
            if op == "application.open":
                app = plan.target or plan.application
                if app:
                    result = self.os_manager.inspect_application(app)
                    if result.get("running"):
                        return ActionPlan(
                            operation=plan.operation,
                            target=app,
                            application=app,
                            confidence=0.9,
                            parameters={**plan.parameters, "already_running": True, "recovery_verified": True},
                            reason=f"Recovery: {app} is actually running (re-observation)",
                            source="RecoveryEngine:state_reobservation",
                        )

            elif op == "application.close":
                app = plan.target or plan.application
                if app:
                    result = self.os_manager.inspect_application(app)
                    if not result.get("running"):
                        return ActionPlan(
                            operation=plan.operation,
                            target=app,
                            application=app,
                            confidence=0.9,
                            parameters={**plan.parameters, "already_closed": True, "recovery_verified": True},
                            reason=f"Recovery: {app} is actually closed (re-observation)",
                            source="RecoveryEngine:state_reobservation",
                        )

            elif op in ("file.create", "folder.create"):
                target = plan.target
                if target:
                    from pathlib import Path
                    if Path(target).exists():
                        return ActionPlan(
                            operation=plan.operation,
                            target=target,
                            application=plan.application,
                            confidence=0.9,
                            parameters={**plan.parameters, "already_exists": True, "recovery_verified": True},
                            reason=f"Recovery: {target} already exists (re-observation)",
                            source="RecoveryEngine:state_reobservation",
                        )

            elif op == "file.delete":
                target = plan.target
                if target:
                    from pathlib import Path
                    if not Path(target).exists():
                        return ActionPlan(
                            operation=plan.operation,
                            target=target,
                            application=plan.application,
                            confidence=0.9,
                            parameters={**plan.parameters, "already_deleted": True, "recovery_verified": True},
                            reason=f"Recovery: {target} is actually deleted (re-observation)",
                            source="RecoveryEngine:state_reobservation",
                        )

            elif op == "file.move":
                dest = plan.parameters.get("destination")
                if dest:
                    from pathlib import Path
                    if Path(dest).exists():
                        return ActionPlan(
                            operation=plan.operation,
                            target=plan.target,
                            application=plan.application,
                            confidence=0.9,
                            parameters={**plan.parameters, "recovery_verified": True, "destination_verified": dest},
                            reason=f"Recovery: file moved to {dest} (re-observation)",
                            source="RecoveryEngine:state_reobservation",
                        )

        except Exception:
            pass

        return None

    def _try_alternative_app(self, plan: ActionPlan) -> Optional[ActionPlan]:
        """Try alternative application for the same task."""
        # Common alternatives mapping
        alternatives = {
            "chrome": ["Google Chrome", "Microsoft Edge", "Brave Browser"],
            "firefox": ["Mozilla Firefox", "Google Chrome", "Microsoft Edge"],
            "vscode": ["Visual Studio Code", "VS Code"],
            "notepad": ["Notepad", "Notepad++", "VS Code"],
            "excel": ["Microsoft Excel", "LibreOffice Calc"],
            "word": ["Microsoft Word", "LibreOffice Writer"],
        }

        target = (plan.target or plan.application or "").lower()
        for key, alts in alternatives.items():
            if key in target:
                for alt in alts:
                    if alt.lower() != target:
                        return ActionPlan(
                            operation=plan.operation,
                            target=alt,
                            application=alt,
                            confidence=0.75,
                            parameters={**plan.parameters, "alternative_app": True, "original_target": target},
                            reason=f"Recovery: trying alternative application {alt}",
                            source="RecoveryEngine:alternative_application",
                        )

        return None


class RecoveryReplanner:
    """
    Replans workflows after failures using recovery strategies.
    
    Integrates with RecoveryEngine to generate alternative workflow plans
    when individual steps fail.
    """

    def __init__(self, recovery_engine: RecoveryEngine, max_replans: int = 2):
        self.recovery_engine = recovery_engine
        self.max_replans = max_replans

    def replan_on_failure(
        self,
        failed_step_id: str,
        workflow: WorkflowPlan,
        state: WorkflowState,
        execution_result: ActionResult,
    ) -> Optional[WorkflowPlan]:
        """
        Generate a recovery workflow plan for a failed step.
        
        Returns a new WorkflowPlan with the failed step replaced by
        a recovery step, or None if recovery is not possible.
        """
        if state.replans >= self.max_replans:
            return None

        # Find the failed step
        failed_step = None
        for step in workflow.steps:
            if step.step_id == failed_step_id:
                failed_step = step
                break

        if failed_step is None:
            return None

        # Attempt recovery for the failed step
        recovery_result = self.recovery_engine.attempt_recovery(
            step_id=failed_step_id,
            plan=failed_step.plan,
            error=execution_result.error or execution_result.status or "unknown_error",
            execution_result=execution_result,
            workflow_state=state,
        )

        if not recovery_result.recovered or recovery_result.final_plan is None:
            return None

        # Build new workflow with recovered step
        new_steps = []
        for step in workflow.steps:
            if step.step_id == failed_step_id:
                # Replace with recovered step (reset retry/verification)
                from .workflow_models import WorkflowStep
                new_step = WorkflowStep(
                    step_id=step.step_id,
                    plan=recovery_result.final_plan,
                    depends_on=step.depends_on,
                    verification_required=step.verification_required,
                    max_retries=step.max_retries,
                    retryable=step.retryable,
                    metadata={**step.metadata, "recovered": True, "recovery_strategy": recovery_result.strategies_attempted[0].strategy_name if recovery_result.strategies_attempted else "unknown"},
                )
                new_steps.append(new_step)
            else:
                new_steps.append(step)

        # Create new workflow with incremented version
        new_workflow = WorkflowPlan(
            objective=workflow.objective,
            steps=tuple(new_steps),
            workflow_id=workflow.workflow_id,
            version=f"{workflow.version}-recovery{state.replans + 1}",
            metadata={**workflow.metadata, "recovery_applied": True, "recovery_details": recovery_result.to_dict()},
        )

        return new_workflow