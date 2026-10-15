"""Genesis OS — Real-OS scenario runner.

Drives each ``RealOSScenario`` through the real Genesis execution
path and records structured evidence.

Architecture:

    RealOSScenario
        -> ScenarioRunner.run_scenario()
            -> evaluate preconditions
            -> for each RealOSStep:
                -> build decision
                -> ActionPlan.from_decision
                -> ActionExecutor.execute (REAL OSManager, not mock)
                -> independent verifier check
                -> record StepEvidence
            -> evaluate postconditions
            -> run cleanup
            -> RealOSScenarioResult

The runner NEVER uses ``_MockOSManager``. If the OSManager is
unavailable the scenario is marked DEPENDENCY and a clear reason
is recorded.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .contract import (
    CleanupStep,
    EvidenceStrength,
    ExecutionMode,
    ExpectedPostcondition,
    PassPolicy,
    Precondition,
    RealOSCategory,
    RealOSScenario,
    RealOSStep,
    RiskLevel,
    SideEffect,
    VerificationRequirement,
)
from .evidence import (
    CleanupEvidence,
    DispatchStatus,
    EvidenceKind,
    EvidenceRecord,
    ExecutionStatus,
    FailureTaxonomy,
    RealOSRunSummary,
    RealOSScenarioResult,
    StepEvidence,
    collect_environment_metadata,
)
from .verifiers import (
    NAMED_VERIFIERS,
    VerifierResult,
    call_verifier,
)

LOGGER = logging.getLogger("benchmark_real_os")

CAPABILITY_DISPATCH_TABLE: Dict[str, str] = {
    # Map scenario "intent" strings to OSManager method names.
    "application.open": "open_application",
    "application.close": "close_application",
    "application.inspect": "inspect_application",
    "application.list": "list_applications",
    "application.is_running": "application_running",
    "file.create": "create_file",
    "file.read": "read_file",
    "file.inspect": "inspect_file",
    "file.copy": "copy_file",
    "file.move": "move_file",
    "file.rename": "rename_file",
    "file.delete": "delete_file",
    "file.hash": "hash_file",
    "file.search": "search_file",
    "file.open": "open_file",
    "folder.create": "create_folder",
    "folder.inspect": "inspect_folder",
    "folder.delete": "delete_folder",
    "browser.open_url": "open_url",
    "browser.search": "web_search",
    "browser.get_title": "browser_get_title",
    "browser.get_url": "browser_get_url",
    "browser.extract": "browser_extract",
    "system.status": "system_status",
    "system.process.list": "list_processes",
    "process.inspect": "inspect_process",
    "process.list": "list_processes",
    "clipboard.copy": "clipboard_copy",
    "clipboard.paste": "clipboard_paste",
    "screen.capture": "screenshot",
    "document.create": "doc_create",
    "document.read": "doc_read",
    "document.edit": "doc_edit",
    "document.inspect": "doc_inspect",
    "document.verify": "doc_verify",
    "spreadsheet.inspect": "sheet_inspect",
    "spreadsheet.sort": "sheet_sort",
    "spreadsheet.create_from_dicts": "sheet_create_from_dicts",
    "spreadsheet.read": "sheet_read",
    "hardware.battery": "battery_status",
    "hardware.stats": "hardware_stats",
}


# ============================================================
# SCENARIO RUNNER
# ============================================================


class RealOSBenchmark:
    """Top-level runner that drives every scenario and produces
    a ``RealOSRunSummary``."""

    def __init__(
        self,
        workspace_root: Optional[str] = None,
        platform_filter: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(
            workspace_root
            or os.environ.get(
                "GENESIS_REAL_OS_WORKSPACE",
                os.path.join(tempfile_default(), "genesis_real_os_workspace"),
            )
        )
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.platform_filter = (
            platform_filter
            or (
                "windows"
                if platform.system().lower().startswith("win")
                else platform.system().lower()
            )
        )
        self.osm = None
        self.executor = None
        self.router = None
        self.osm_init_error: Optional[str] = None
        self._init_runtime()
        self.results: List[RealOSScenarioResult] = []

    # ---------------------------------------------------------
    # RUNTIME INITIALISATION
    # ---------------------------------------------------------

    def _init_runtime(self) -> None:
        """Build the REAL OSManager and ActionExecutor.

        We do NOT use ``_MockOSManager``. If the OSManager cannot
        be imported we record the failure and let every scenario
        fail with taxonomy=DEPENDENCY."""

        # Ensure backend dir is on sys.path
        backend_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        try:
            from agents.workflow_decision import WorkflowDecisionEngine  # noqa: E402
            self.router = WorkflowDecisionEngine()
        except Exception as exc:  # pragma: no cover
            self.router = None
            self.osm_init_error = f"router initialization failed: {type(exc).__name__}: {exc}"
            LOGGER.warning(self.osm_init_error)
            return

        try:
            from genesis_os.os_manager import OSManager  # noqa: E402
            self.osm = OSManager()
        except Exception as exc:  # pragma: no cover
            self.osm = None
            self.osm_init_error = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("OSManager unavailable: %s", self.osm_init_error)
            return

        try:
            from genesis_os.action_executor import ActionExecutor  # noqa: E402
            # Bind to the REAL OSManager. The legacy 500-task
            # benchmark uses _MockOSManager; we do NOT.
            self.executor = ActionExecutor(self.osm)
        except Exception as exc:  # pragma: no cover
            self.executor = None
            LOGGER.warning("ActionExecutor unavailable: %s", exc)

    # ---------------------------------------------------------
    # MAIN ENTRY POINTS
    # ---------------------------------------------------------

    def run_scenarios(self, scenarios: List[RealOSScenario]) -> List[RealOSScenarioResult]:
        for scenario in scenarios:
            self.results.append(self.run_scenario(scenario))
        return self.results

    def summary(self) -> RealOSRunSummary:
        return self._build_summary(self.results)

    def run_scenario(self, scenario: RealOSScenario) -> RealOSScenarioResult:
        started_at = _utc_now()
        step_evidence: List[StepEvidence] = []
        cleanup_evidence: List[CleanupEvidence] = []
        all_records: List[EvidenceRecord] = []
        status = "PASS"
        failure_reason: Optional[str] = None
        failure_taxonomy = FailureTaxonomy.UNKNOWN
        actual_capability: Optional[str] = None

        if scenario.platform and scenario.platform != self.platform_filter:
            return RealOSScenarioResult(
                scenario_id=scenario.scenario_id,
                name=scenario.name,
                mode=scenario.execution_mode,
                started_at=started_at,
                finished_at=_utc_now(),
                duration=0.0,
                passed=False,
                status="SKIPPED",
                steps=[],
                evidence=[],
                cleanup=[],
                failure_reason=(
                    f"platform {scenario.platform!r} does not match host "
                    f"{self.platform_filter!r}"
                ),
                failure_taxonomy=FailureTaxonomy.PLATFORM,
                risk=scenario.risk_level.value,
                artifacts=list(scenario.artifacts),
                natural_language_request=scenario.natural_language_request,
                expected_capabilities=list(scenario.expected_capabilities),
                category=scenario.category.value,
            )

        if self.osm is None:
            return RealOSScenarioResult(
                scenario_id=scenario.scenario_id,
                name=scenario.name,
                mode=scenario.execution_mode,
                started_at=started_at,
                finished_at=_utc_now(),
                duration=0.0,
                passed=False,
                status="DEPENDENCY",
                steps=[],
                evidence=[],
                cleanup=[],
                failure_reason=(
                    "OSManager failed to initialise: "
                    f"{self.osm_init_error}"
                ),
                failure_taxonomy=FailureTaxonomy.DEPENDENCY,
                risk=scenario.risk_level.value,
                artifacts=list(scenario.artifacts),
                natural_language_request=scenario.natural_language_request,
                expected_capabilities=list(scenario.expected_capabilities),
                category=scenario.category.value,
            )

        workspace = self._prepare_workspace(scenario)

        # PRECONDITIONS
        precondition_ok = True
        for pre in scenario.preconditions:
            ok, detail = _evaluate_precondition(pre)
            all_records.append(
                EvidenceRecord(
                    timestamp=_utc_now(),
                    scenario_id=scenario.scenario_id,
                    step_id="preconditions",
                    event_type=EvidenceKind.OBSERVATION,
                    post_state={"passed": ok, "detail": detail, "description": pre.description},
                    evidence_strength=EvidenceStrength.LEVEL_3
                    if ok
                    else EvidenceStrength.LEVEL_1,
                )
            )
            if not ok:
                precondition_ok = False
                status = "FAIL"
                failure_reason = (
                    f"precondition failed: {pre.description} ({detail})"
                )
                failure_taxonomy = FailureTaxonomy.PRECONDITION

        # STEPS
        previous_step_targets: Dict[str, str] = {}
        if precondition_ok:
            for step in scenario.steps:
                step_record = self._run_step(scenario, step, workspace, previous_step_targets)
                step_evidence.append(step_record)
                all_records.extend(step_record.records)
                actual_capability = (
                    actual_capability or step_record.capability
                )
                if step_record.execution_status == ExecutionStatus.TIMED_OUT:
                    status = "TIMED_OUT"
                    failure_reason = step_record.failure_reason or "timed out"
                    failure_taxonomy = FailureTaxonomy.TIMEOUT
                    break
                if step_record.execution_status == ExecutionStatus.EXCEPTION:
                    status = "EXCEPTION"
                    failure_reason = step_record.failure_reason
                    failure_taxonomy = FailureTaxonomy.PROVIDER
                    break
                if not step_record.verification_pass:
                    # BEST_EFFORT: missing verification does not auto-fail
                    # if the dispatch reached the real provider.
                    if (scenario.pass_policy == PassPolicy.BEST_EFFORT
                            and step_record.dispatch_status == DispatchStatus.REAL_PROVIDER):
                        pass  # allow through
                    else:
                        status = "FAIL"
                        failure_reason = (
                            step_record.failure_reason
                            or "postcondition not independently verified"
                        )
                        failure_taxonomy = (
                            FailureTaxonomy.VERIFICATION
                            if step_record.execution_pass
                            else FailureTaxonomy.DISPATCH
                        )

        # GLOBAL POSTCONDITIONS
        verification_summary: Dict[str, Any] = {
            "checks": [],
            "all_passed": True,
        }
        if precondition_ok and status == "PASS":
            for post in scenario.expected_postconditions:
                ok, detail, evidence = _evaluate_postcondition(post)
                verification_summary["checks"].append(
                    {
                        "description": post.description,
                        "passed": ok,
                        "detail": detail,
                    }
                )
                all_records.append(
                    EvidenceRecord(
                        timestamp=_utc_now(),
                        scenario_id=scenario.scenario_id,
                        step_id="global_postcondition",
                        event_type=(
                            EvidenceKind.VERIFICATION
                            if ok
                            else EvidenceKind.OBSERVATION
                        ),
                        evidence_strength=EvidenceStrength.LEVEL_4
                        if ok
                        else EvidenceStrength.LEVEL_3,
                        post_state={"passed": ok, "detail": detail, **evidence},
                    )
                )
                if not ok:
                    verification_summary["all_passed"] = False
                    status = "FAIL"
                    failure_reason = (
                        f"global postcondition failed: {post.description} "
                        f"({detail})"
                    )
                    failure_taxonomy = FailureTaxonomy.VERIFICATION

        # CLEANUP
        cleanup_ok = True
        for cl in scenario.cleanup:
            cl_ok, cl_detail, cl_err = self._run_cleanup(cl)
            cleanup_evidence.append(
                CleanupEvidence(
                    description=cl.description,
                    success=cl_ok,
                    detail=cl_detail,
                    error=cl_err,
                )
            )
            if not cl_ok:
                cleanup_ok = False

        finished_at = _utc_now()
        duration = _duration_seconds(started_at, finished_at)

        # FINAL VERDICT
        passed = (
            status == "PASS"
            and cleanup_ok
            and all(
                step.execution_status == ExecutionStatus.OK
                and step.verification_pass
                for step in step_evidence
            )
            and verification_summary["all_passed"]
        )
        if not cleanup_ok and status == "PASS":
            status = "FAILED_CLEANUP"
        if not passed and status == "PASS":
            status = "FAIL"
            failure_reason = failure_reason or "One or more execution or verification gates failed."
            failure_taxonomy = failure_taxonomy or FailureTaxonomy.VERIFICATION

        result_obj = RealOSScenarioResult(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            mode=scenario.execution_mode,
            started_at=started_at,
            finished_at=finished_at,
            duration=duration,
            passed=passed,
            status=status,
            steps=step_evidence,
            evidence=all_records,
            cleanup=cleanup_evidence,
            failure_reason=failure_reason,
            failure_taxonomy=failure_taxonomy,
            verification_summary=verification_summary,
            risk=scenario.risk_level.value,
            artifacts=list(scenario.artifacts),
            environment={"workspace": str(workspace)},
            natural_language_request=scenario.natural_language_request,
            expected_capabilities=list(scenario.expected_capabilities),
            actual_capability=actual_capability,
            category=scenario.category.value,
        )
        return result_obj

    # ---------------------------------------------------------
    # WORKSPACE
    # ---------------------------------------------------------

    def _prepare_workspace(self, scenario: RealOSScenario) -> Path:
        """Create an isolated per-scenario workspace.

        The workspace is cleaned before each run so that leftover
        artifacts from previous runs do not cause false failures
        (e.g. "already_exists")."""

        ws = self.workspace_root / scenario.scenario_id
        if ws.exists():
            import shutil
            shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    # ---------------------------------------------------------
    # STEP SETUP
    # ---------------------------------------------------------

    def _handle_step_setup(self, step: RealOSStep, workspace: Path) -> None:
        """Pre-create test files from _setup_write / _setup_path parameters.

        This runs BEFORE the dispatch so the step can read/edit an existing file."""
        params = step.parameters or {}
        setup_path = params.get("_setup_path")
        setup_content = params.get("_setup_write")
        if setup_path and setup_content is not None:
            # Resolve relative paths against workspace
            p = Path(setup_path) if os.path.isabs(setup_path) else workspace / setup_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(setup_content), encoding="utf-8")

        # Pre-create a spreadsheet from _setup_sheet_path / _setup_sheet_rows
        setup_sheet_path = params.get("_setup_sheet_path")
        setup_sheet_rows = params.get("_setup_sheet_rows")
        if setup_sheet_path and setup_sheet_rows:
            try:
                from openpyxl import Workbook
                p = Path(setup_sheet_path) if os.path.isabs(setup_sheet_path) else workspace / setup_sheet_path
                p.parent.mkdir(parents=True, exist_ok=True)
                wb = Workbook()
                ws = wb.active
                for row in setup_sheet_rows:
                    ws.append(row)
                wb.save(str(p))
                wb.close()
            except Exception:
                pass

    # ---------------------------------------------------------
    # STEP EXECUTION
    # ---------------------------------------------------------

    def _run_step(
        self,
        scenario: RealOSScenario,
        step: RealOSStep,
        workspace: Path,
        previous_step_targets: Optional[Dict[str, str]] = None,
    ) -> StepEvidence:
        step_id = step.description or step.intent
        records: List[EvidenceRecord] = []
        started = _utc_now()
        step_evidence = StepEvidence(
            step_id=step_id,
            description=step.description,
            capability=step.intent,
            target=step.target,
            started_at=started,
        )

        # SETUP: pre-create test files from _setup_write / _setup_path
        self._handle_step_setup(step, workspace)

        # Resolve target path relative to workspace for non-absolute targets
        # Skip resolution for operations where target is a name, not a path,
        # or where the target is a URL.
        _NAME_TARGET_OPS = {
            "application.open", "application.close", "application.inspect",
            "process.inspect", "process.list",
            "gui.focus_window", "gui.inspect_window",
        }
        original_target = step.target
        if (step.target and not os.path.isabs(step.target)
                and step.intent not in _NAME_TARGET_OPS
                and not step.target.startswith(("http://", "https://", "file://"))):
            resolved_target = str(workspace / step.target)
            step.target = resolved_target

        # SEMANTIC: route raw natural-language input through the real router.
        decision = self._build_decision(scenario, step, workspace, previous_step_targets)
        routing_text = step.routing_text
        if not routing_text:
            routing_text = (
                scenario.natural_language_request
                if len(scenario.steps) == 1
                else step.description
            )
        router_decision = None
        router_error = None
        try:
            router_decision = self._route_natural_language(routing_text)
        except Exception as exc:
            router_error = f"{type(exc).__name__}: {exc}"
        routing_pass = self._validate_routing(router_decision, step.intent)
        step_evidence.semantic_pass = routing_pass
        records.append(
            EvidenceRecord(
                timestamp=_utc_now(),
                scenario_id=scenario.scenario_id,
                step_id=step_id,
                event_type=EvidenceKind.SEMANTIC,
                capability=step.intent,
                target=step.target,
                dispatch_status=DispatchStatus.NOT_DISPATCHED,
                post_state={
                    "routing_input": routing_text,
                    "router_decision": _safe_json(router_decision),
                    "router_error": router_error,
                    "execution_decision": _safe_json(decision),
                    "routing_pass": routing_pass,
                },
                evidence_strength=(
                    EvidenceStrength.LEVEL_2 if routing_pass else EvidenceStrength.LEVEL_1
                ),
            )
        )

        if not routing_pass:
            finished = _utc_now()
            step_evidence.execution_status = ExecutionStatus.FAILED
            step_evidence.finished_at = finished
            step_evidence.duration = _duration_seconds(started, finished)
            step_evidence.failure_reason = (
                "Natural-language routing did not produce the expected "
                f"Level 3 intent {step.intent!r}."
            )
            step_evidence.failure_taxonomy = FailureTaxonomy.UNDERSTANDING
            records.append(
                EvidenceRecord(
                    timestamp=_utc_now(),
                    scenario_id=scenario.scenario_id,
                    step_id=step_id,
                    event_type=EvidenceKind.OBSERVATION,
                    capability=step.intent,
                    verification_status=ExecutionStatus.FAILED,
                    post_state={
                        "routing_input": routing_text,
                        "router_decision": _safe_json(router_decision),
                        "router_error": router_error,
                    },
                    evidence_strength=EvidenceStrength.LEVEL_1,
                )
            )
            step_evidence.records = records
            step.target = original_target
            return step_evidence

        # DISPATCH: actually call the OSManager method
        try:
            dispatch_status, dispatch_payload, exec_result = self._dispatch(
                scenario, step, decision, workspace
            )
        except Exception as exc:  # pragma: no cover
            tb = traceback.format_exc()
            finished = _utc_now()
            step_evidence.execution_status = ExecutionStatus.EXCEPTION
            step_evidence.finished_at = finished
            step_evidence.duration = _duration_seconds(started, finished)
            step_evidence.failure_reason = f"dispatch exception: {exc}"
            step_evidence.failure_taxonomy = FailureTaxonomy.DISPATCH
            records.append(
                EvidenceRecord(
                    timestamp=_utc_now(),
                    scenario_id=scenario.scenario_id,
                    step_id=step_id,
                    event_type=EvidenceKind.EXCEPTION,
                    capability=step.intent,
                    exception=tb,
                    evidence_strength=EvidenceStrength.LEVEL_2,
                )
            )
            return step_evidence

        records.append(
            EvidenceRecord(
                timestamp=_utc_now(),
                scenario_id=scenario.scenario_id,
                step_id=step_id,
                event_type=EvidenceKind.DISPATCH,
                capability=step.intent,
                target=step.target,
                dispatch_status=dispatch_status,
                post_state=_safe_json(dispatch_payload),
                evidence_strength=(
                    EvidenceStrength.LEVEL_2
                    if dispatch_status == DispatchStatus.REAL_PROVIDER
                    else EvidenceStrength.LEVEL_1
                ),
            )
        )

        step_evidence.dispatch_status = dispatch_status

        # EXECUTION: did the provider return a structurally-valid
        # success?
        execution_pass = (
            isinstance(exec_result, dict)
            and exec_result.get("success") is True
        )
        step_evidence.execution_pass = execution_pass
        if execution_pass:
            step_evidence.execution_status = ExecutionStatus.OK
        elif (
            isinstance(exec_result, dict)
            and exec_result.get("status") == "timed_out"
        ):
            step_evidence.execution_status = ExecutionStatus.TIMED_OUT
        else:
            step_evidence.execution_status = ExecutionStatus.FAILED

        records.append(
            EvidenceRecord(
                timestamp=_utc_now(),
                scenario_id=scenario.scenario_id,
                step_id=step_id,
                event_type=EvidenceKind.EXECUTION,
                capability=step.intent,
                target=step.target,
                dispatch_status=dispatch_status,
                execution_status=step_evidence.execution_status,
                post_state=_safe_json(exec_result),
                stdout=(
                    exec_result.get("stdout")
                    if isinstance(exec_result, dict)
                    else None
                ),
                stderr=(
                    exec_result.get("stderr")
                    if isinstance(exec_result, dict)
                    else None
                ),
                exception=(
                    exec_result.get("traceback")
                    if isinstance(exec_result, dict)
                    else None
                ),
                verification_reason=(
                    exec_result.get("verification_reason")
                    if isinstance(exec_result, dict)
                    else None
                ),
                evidence_strength=EvidenceStrength.LEVEL_2,
            )
        )

        # VERIFICATION: independent post-condition checks
        verification_pass = False
        verification_reason = "no postconditions defined"
        verification_evidence: Dict[str, Any] = {}
        if execution_pass:
            verification_pass = True  # Will be set to False if any postcondition fails
            for post in step.expected_postconditions:
                # Resolve artifact_path relative to workspace
                resolved_post = post.model_copy()
                if post.artifact_path and not os.path.isabs(post.artifact_path):
                    resolved_post.artifact_path = str(workspace / post.artifact_path)
                ok, detail, evidence = _evaluate_postcondition(resolved_post)
                verification_pass = verification_pass and ok
                verification_reason = (
                    verification_reason if verification_pass else detail
                )
                verification_evidence.update(evidence)
                records.append(
                    EvidenceRecord(
                        timestamp=_utc_now(),
                        scenario_id=scenario.scenario_id,
                        step_id=step_id,
                        event_type=(
                            EvidenceKind.VERIFICATION if ok else EvidenceKind.OBSERVATION
                        ),
                        capability=step.intent,
                        target=post.artifact_path,
                        verification_status=(
                            ExecutionStatus.OK if ok else ExecutionStatus.FAILED
                        ),
                        post_state={"passed": ok, "detail": detail, **evidence},
                        evidence_strength=(
                            EvidenceStrength.LEVEL_4 if ok else EvidenceStrength.LEVEL_3
                        ),
                    )
                )
        else:
            verification_pass = False
            # Extract real diagnostic details from the executor result
            # instead of emitting a generic message.
            _exec_error = (
                exec_result.get("error")
                if isinstance(exec_result, dict)
                else None
            )
            _exec_message = (
                exec_result.get("message")
                if isinstance(exec_result, dict)
                else None
            )
            _exec_status = (
                exec_result.get("status")
                if isinstance(exec_result, dict)
                else None
            )
            _exec_final = (
                exec_result.get("final_state")
                if isinstance(exec_result, dict)
                else None
            )
            _parts = []
            if _exec_final:
                _parts.append(f"final_state={_exec_final}")
            if _exec_status:
                _parts.append(f"status={_exec_status}")
            if _exec_message:
                _parts.append(f"message={_exec_message}")
            if _exec_error:
                _parts.append(f"error={_exec_error}")
            verification_reason = (
                "execution did not succeed: "
                + "; ".join(_parts)
                if _parts
                else "execution did not succeed; independent verification skipped"
            )

        step_evidence.verification_pass = verification_pass
        step_evidence.evidence_strength = _step_evidence_strength(records)

        if not verification_pass:
            step_evidence.failure_reason = (
                step_evidence.failure_reason or verification_reason
            )
            if step_evidence.failure_taxonomy == FailureTaxonomy.UNKNOWN:
                step_evidence.failure_taxonomy = (
                    FailureTaxonomy.VERIFICATION
                    if step_evidence.execution_pass
                    else FailureTaxonomy.OBSERVATION
                )

        finished = _utc_now()
        step_evidence.finished_at = finished
        step_evidence.duration = _duration_seconds(started, finished)
        step_evidence.records = records
        # Track this step's resolved target for compound scenario coordination
        if previous_step_targets is not None and step.target is not None:
            previous_step_targets[step.intent] = step.target
        # Restore original target for cleanup
        step.target = original_target
        return step_evidence

    # ---------------------------------------------------------
    # DECISION BUILDING + ROUTING VALIDATION
    # ---------------------------------------------------------

    def _build_decision(
        self,
        scenario: RealOSScenario,
        step: RealOSStep,
        workspace: Optional[Path] = None,
        previous_step_targets: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        parameters = dict(step.parameters or {})
        if step.target is not None:
            parameters.setdefault("target", step.target)
        parameters["confirmed"] = True

        # Map _setup_sheet_path → source for spreadsheet scenarios
        # that use the setup parameter as the input file.
        if "source" not in parameters and "_setup_sheet_path" in parameters:
            parameters["source"] = parameters["_setup_sheet_path"]

        # For spreadsheet.sort with no explicit source, the target
        # is the output file and the source must be provided via
        # _setup_sheet_path or be the same as target (in-place sort).
        if step.intent == "spreadsheet.sort" and "source" not in parameters:
            # For compound scenarios, the source is the previous step's output.
            if previous_step_targets:
                # Find the most recent step target that looks like a spreadsheet.
                for prev_intent, prev_target in reversed(previous_step_targets.items()):
                    if prev_target and (prev_target.endswith(".xlsx") or prev_target.endswith(".csv")):
                        parameters["source"] = prev_target
                        break
            # Fallback: use target (in-place sort)
            if "source" not in parameters:
                parameters["source"] = step.target

        if step.intent == "spreadsheet.create_from_dicts" and "data" not in parameters:
            headers = parameters.get("headers", [])
            rows = parameters.get("rows", [])
            parameters["data"] = [
                dict(zip(headers, row)) for row in rows
            ] if headers and rows else []

        # Resolve relative file paths in parameters so the
        # ActionExecutor (which reads parameters directly) gets
        # absolute paths.
        if workspace is not None:
            for key in ("source", "destination", "output"):
                val = parameters.get(key)
                if val and not os.path.isabs(val):
                    parameters[key] = str(workspace / val)

        # Also resolve the top-level target for operations that
        # read it directly (file.read, file.delete, file.create, etc.)
        # Skip resolution for operations where target is a name, not a path,
        # or where the target is a URL.
        _NAME_TARGET_OPS = {
            "application.open", "application.close", "application.inspect",
            "process.inspect", "process.list",
            "gui.focus_window", "gui.inspect_window",
        }
        target = step.target
        if (workspace is not None and target and not os.path.isabs(target)
                and step.intent not in _NAME_TARGET_OPS
                and not target.startswith(("http://", "https://", "file://"))):
            target = str(workspace / target)

        return {
            "level": 3,
            "mode": "os",
            "operation": step.intent,
            "intent": step.intent,
            "target": target,
            "task": scenario.natural_language_request,
            "parameters": parameters,
            "confidence": 1.0,
            "confirmed": True,
        }

    def _route_natural_language(self, text: str) -> Optional[Dict[str, Any]]:
        if self.router is None:
            return None
        return self.router.decide(text)

    def _validate_routing(self, decision: Dict[str, Any], expected_intent: str) -> bool:
        if not isinstance(decision, dict):
            return False
        if decision.get("level") != 3:
            return False
        aliases = {
            "system.process.list": "process.list",
        }
        expected = aliases.get(expected_intent, expected_intent)
        actual = decision.get("operation") or decision.get("intent")
        return actual == expected

    # ---------------------------------------------------------
    # DISPATCH
    # ---------------------------------------------------------

    def _dispatch(
        self,
        scenario: RealOSScenario,
        step: RealOSStep,
        decision: Dict[str, Any],
        workspace: Path,
    ) -> Tuple[DispatchStatus, Dict[str, Any], Any]:
        """Invoke the real capability through ActionExecutor.

        The benchmark uses the production executor exclusively; it does
        not silently fall back to a direct OSManager call.
        """

        # Dispatch exclusively through ActionExecutor.
        try:
            from genesis_os.action_plan import (
                ActionPlan,
                ActionPlanValidationError,
            )
        except Exception:
            ActionPlan = None
            ActionPlanValidationError = Exception

        if self.executor is not None and ActionPlan is not None:
            try:
                plan = ActionPlan.from_decision(decision)
                result = self.executor.execute(plan)
                payload = (
                    result.to_dict()
                    if hasattr(result, "to_dict")
                    else _safe_json(result)
                )
                # If the executor returned requires_runtime_resolution,
                # that's still a real dispatch outcome.
                return (
                    DispatchStatus.REAL_PROVIDER,
                    payload,
                    payload,
                )
            except (ActionPlanValidationError, ValueError) as exc:
                LOGGER.debug(
                    "ActionExecutor rejected plan %s: %s",
                    step.intent,
                    exc,
                )
            except Exception as exc:
                # Unexpected exception in ActionExecutor — capture
                # the real error rather than silently falling through.
                tb = traceback.format_exc()
                return (
                    DispatchStatus.REAL_PROVIDER,
                    {"error": f"{type(exc).__name__}: {exc}", "traceback": tb},
                    {"success": False, "error": str(exc), "traceback": tb},
                )

        return (
            DispatchStatus.NOT_DISPATCHED,
            {
                "error": (
                    f"ActionExecutor rejected {step.intent!r}; "
                    "direct OSManager fallback is disabled"
                )
            },
            {
                "success": False,
                "error": f"ActionExecutor rejected {step.intent!r}",
            },
        )

    # ---------------------------------------------------------
    # CLEANUP
    # ---------------------------------------------------------

    def _run_cleanup(self, step: CleanupStep) -> Tuple[bool, str, Optional[str]]:
        if step.action is not None:
            try:
                step.action()
            except Exception as exc:
                return False, f"cleanup action raised: {exc}", str(exc)
        if step.verifier is None:
            return True, "no verifier (cleanup recorded only)", None
        ok, detail, evidence = _evaluate_verifier_callable(step.verifier, [])
        if not ok:
            return False, detail, None
        return True, detail, None

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    def _build_summary(self, results: List[RealOSScenarioResult]) -> RealOSRunSummary:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = sum(
            1 for r in results
            if not r.passed and r.status != "SKIPPED"
        )
        timed_out = sum(1 for r in results if r.status == "TIMED_OUT")
        skipped = sum(1 for r in results if r.status == "SKIPPED")
        cleanup_failures = sum(1 for r in results if r.status == "FAILED_CLEANUP")
        unverified = sum(1 for r in results if r.status == "UNVERIFIED")
        semantic_passes = sum(1 for r in results if r.semantic_pass)
        execution_passes = sum(1 for r in results if r.execution_pass)
        verification_passes = sum(1 for r in results if r.verification_pass)
        real_os_passes = sum(
            1
            for r in results
            if r.passed
            and any(
                rec.evidence_strength >= 4
                for step in r.steps
                for rec in step.records
            )
        )
        pass_rate = passed / total if total else 0.0
        real_os_pass_rate = real_os_passes / total if total else 0.0

        evidence_level_distribution: Dict[str, int] = {}
        for r in results:
            for step in r.steps:
                lvl = str(int(step.evidence_strength))
                evidence_level_distribution[lvl] = (
                    evidence_level_distribution.get(lvl, 0) + 1
                )

        # Capability coverage
        capability_coverage: Dict[str, int] = {}
        for r in results:
            for cap in r.expected_capabilities:
                capability_coverage[cap] = capability_coverage.get(cap, 0) + 1

        category_pass_rate: Dict[str, float] = {}
        for r in results:
            category_pass_rate.setdefault(r.category, []).append(1 if r.passed else 0)
        for cat, vals in list(category_pass_rate.items()):
            category_pass_rate[cat] = (sum(vals) / len(vals)) if vals else 0.0

        failures: List[Dict[str, Any]] = []
        for r in results:
            if r.passed:
                continue
            failures.append(
                {
                    "scenario_id": r.scenario_id,
                    "name": r.name,
                    "category": r.category,
                    "status": r.status,
                    "failure_reason": r.failure_reason,
                    "failure_taxonomy": r.failure_taxonomy.value,
                    "natural_language_request": r.natural_language_request,
                }
            )

        return RealOSRunSummary(
            started_at=(results[0].started_at if results else _utc_now()),
            finished_at=(results[-1].finished_at if results else _utc_now()),
            duration=sum(r.duration for r in results),
            total=total,
            passed=passed,
            failed=failed,
            timed_out=timed_out,
            skipped=skipped,
            cleanup_failures=cleanup_failures,
            unverified=unverified,
            semantic_passes=semantic_passes,
            execution_passes=execution_passes,
            verification_passes=verification_passes,
            real_os_passes=real_os_passes,
            pass_rate=pass_rate,
            real_os_pass_rate=real_os_pass_rate,
            evidence_level_distribution=evidence_level_distribution,
            capability_coverage=capability_coverage,
            category_pass_rate=category_pass_rate,
            environment=collect_environment_metadata(),
            failures=failures,
        )


# ============================================================
# HELPERS
# ============================================================


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(start_iso: str, end_iso: str) -> float:
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return max(0.0, (end - start).total_seconds())
    except Exception:
        return 0.0


def _safe_json(obj: Any) -> Dict[str, Any]:
    """Serialise an arbitrary object into a JSON-safe dict.

    Falls back to repr when an attribute is not JSON-encodable."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            try:
                json.dumps(v)
                out[k] = v
            except TypeError:
                out[k] = repr(v)
        return out
    if hasattr(obj, "to_dict"):
        try:
            return _safe_json(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return _safe_json(vars(obj))
        except Exception:
            pass
    try:
        json.dumps(obj)
        return {"value": obj}
    except TypeError:
        return {"value": repr(obj)}


def _step_evidence_strength(records: List[EvidenceRecord]) -> EvidenceStrength:
    if not records:
        return EvidenceStrength.LEVEL_0
    return max(records, key=lambda r: int(r.evidence_strength)).evidence_strength


def _evaluate_precondition(pre: Precondition) -> Tuple[bool, str]:
    """Evaluate a Precondition. Returns (passed, detail).

    A scenario that lists a precondition without a callable is
    treated as 'no automated check; assumed true' so the contract
    remains declarative."""

    if pre.verifier is not None:
        ok, detail, _ = _evaluate_verifier_callable(pre.verifier, [])
        return ok, detail
    if pre.verifier_id:
        ok, detail, _ = call_verifier(pre.verifier_id)
        return ok, detail
    return True, "no automated precondition"


def _evaluate_postcondition(post: ExpectedPostcondition) -> VerifierResult:
    if post.verifier is not None:
        return _evaluate_verifier_callable(post.verifier, [])
    if post.verifier_id:
        args: List[Any] = []
        kwargs: Dict[str, Any] = dict(post.verifier_kwargs)
        # Some verifiers take a path as first argument
        if post.artifact_path:
            args.append(post.artifact_path)
        # Pass expected_value as appropriate keyword argument
        if post.expected_value:
            if post.verifier_id in ("verify_file_contains", "verify_text_document",
                                     "verify_docx"):
                kwargs.setdefault("expected_substring", post.expected_value)
            elif post.verifier_id == "verify_clipboard_contains":
                kwargs.setdefault("expected_substring", post.expected_value)
            elif post.verifier_id == "verify_xlsx_value":
                kwargs.setdefault("expected_value", post.expected_value)
            elif post.verifier_id == "verify_file_sha256":
                kwargs.setdefault("expected_sha256", post.expected_value)
        return call_verifier(post.verifier_id, *args, **kwargs)
    return (
        False,
        "postcondition has neither verifier nor verifier_id",
        {},
    )


def _evaluate_verifier_callable(
    fn: Callable[..., VerifierResult], args: List[Any]
) -> VerifierResult:
    try:
        return fn(*args)
    except Exception as exc:
        return False, f"verifier exception: {exc}", {}


def tempfile_default() -> str:
    import tempfile

    return tempfile.gettempdir()


def run_benchmark(
    workspace_root: Optional[str] = None,
    scenarios: Optional[List[RealOSScenario]] = None,
) -> Tuple[List[RealOSScenarioResult], RealOSRunSummary]:
    """Convenience wrapper for a one-shot benchmark run."""

    from .scenarios import REAL_OS_SCENARIOS, COMPOUND_REAL_OS_SCENARIOS

    runner = RealOSBenchmark(workspace_root=workspace_root)
    scenarios_to_run = (
        scenarios
        if scenarios is not None
        else (REAL_OS_SCENARIOS + COMPOUND_REAL_OS_SCENARIOS)
    )
    results = runner.run_scenarios(scenarios_to_run)
    summary = runner.summary()
    return results, summary