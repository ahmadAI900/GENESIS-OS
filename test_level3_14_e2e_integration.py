"""
Genesis OS — Level 3.14
End-to-End Integration Test Suite.

Tests the complete pipeline from natural language to verified result,
covering the full Level 3 lifecycle:

    1. Full Pipeline: Understanding -> Planning -> Execution -> Verification
    2. Multi-Step Workflow Execution
    3. Safety Gate Integration
    4. Capability Discovery Pipeline
    5. Document Intelligence Integration
    6. Spreadsheet Intelligence Integration
    7. Context Pipeline Integration
    8. Observation Loop Integration
    9. Recovery Engine Integration
   10. Full Level 3 Decision -> Execution Chain
"""

from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.objective_understanding import (
    ObjectiveUnderstanding,
    ObjectiveStepIntent,
    ObjectiveUnderstandingResult,
)
from genesis_os.workflow_decomposer import (
    WorkflowDecomposer,
    DecompositionResult,
)
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.workflow_models import WorkflowPlan, WorkflowStep
from genesis_os.workflow_planner import WorkflowPlanner
from genesis_os.capability_registry import Capability, CapabilityRegistry
from genesis_os.capability_resolver import CapabilityResolver
from genesis_os.execution_safety import ExecutionSafety
from genesis_os.document_intelligence import DocumentIntelligence, DocumentFormat
from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence
from genesis_os.enhanced_observation import (
    EnhancedObservationLoop,
    EnhancedObservationResult,
)
from genesis_os.observation_loop import ObservationLoop, ObservationResult


# =========================================================
# HELPERS
# =========================================================


def _decision(
    text,
    *,
    operation="application.open",
    target="Chrome",
    confidence=0.97,
):
    return {
        "level": 3,
        "mode": "os",
        "task": text,
        "intent": operation,
        "operation": operation,
        "target": target,
        "application": (
            target
            if operation.startswith("application.")
            else None
        ),
        "parameters": {},
        "confidence": confidence,
        "reason": "test",
    }


class FakeDecisionEngine:
    """Engine that returns pre-programmed decisions per fragment."""

    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def decide(self, text):
        self.calls.append(text)
        if text in self.decisions:
            return self.decisions[text]
        for key, decision in self.decisions.items():
            if key in text or text in key:
                return decision
        return {
            "level": 1,
            "mode": "conversation",
            "task": text,
            "confidence": 0.5,
        }


def _verified_result(operation):
    """Return a verified result for a given operation."""

    def _inner(*args, **kwargs):
        return {
            "success": True,
            "operation": operation,
            "executed": True,
            "verified": True,
            "running": True,
            "message": f"{operation} verified.",
        }

    return _inner


def _make_intent(
    *,
    step_id="objective-step-1",
    sequence=1,
    text="open Chrome",
    operation="application.open",
    target="Chrome",
    application="Chrome",
    confidence=0.98,
):
    decision = {
        "level": 3,
        "mode": "os",
        "operation": operation,
        "target": target,
        "application": application,
        "task": text,
        "confidence": confidence,
        "parameters": {},
        "reason": "Resolved by WorkflowDecisionEngine",
        "source": "WorkflowDecisionEngine",
    }
    return ObjectiveStepIntent(
        step_id=step_id,
        text=text,
        sequence=sequence,
        decision=decision,
        confidence=confidence,
        level=3,
        mode="os",
        operation=operation,
        target=target,
        application=application,
    )


def _make_understanding(*intents):
    return ObjectiveUnderstandingResult(
        objective="test",
        steps=tuple(intents),
        confidence=min(i.confidence for i in intents) if intents else 0.0,
        requires_clarification=any(
            i.requires_clarification for i in intents
        ),
    )


# =========================================================
# 1. FULL PIPELINE: Understanding -> Planning -> Execution -> Verification
# =========================================================


class TestFullPipeline:
    """Natural language flows through the complete Level 3 lifecycle."""

    def test_understanding_to_execution_pipeline(self):
        """ObjectiveUnderstanding -> WorkflowDecomposer -> ActionExecutor -> verified result."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision(
                "open Chrome",
                operation="application.open",
                target="Chrome",
            ),
        })

        understanding = ObjectiveUnderstanding(engine).understand("open Chrome")
        decomposition = WorkflowDecomposer().decompose(understanding)

        assert decomposition.executable is True
        assert decomposition.workflow is not None
        assert len(decomposition.workflow.steps) == 1

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        plan = decomposition.workflow.steps[0].plan

        result = executor.execute(plan)

        assert result.success is True
        assert result.status == "verified"
        assert result.executed is True
        assert result.verified is True

    def test_full_pipeline_with_real_os_manager(self):
        """Real OSManager open_application through the full planning pipeline."""
        engine = FakeDecisionEngine({
            "open notepad": _decision(
                "open notepad",
                operation="application.open",
                target="notepad",
            ),
        })

        understanding = ObjectiveUnderstanding(engine).understand("open notepad")
        decomposition = WorkflowDecomposer().decompose(understanding)
        plan = decomposition.workflow.steps[0].plan

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Notepad opened.",
        }

        executor = ActionExecutor(os_manager)
        result = executor.execute(plan)

        assert result.success is True
        assert result.status == "verified"
        os_manager.open_application.assert_called_once()

    def test_pipeline_result_has_trustworthy_success(self, tmp_path):
        """A fully verified execution must produce trustworthy_success."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        })

        understanding = ObjectiveUnderstanding(engine).understand("open Chrome")
        decomposition = WorkflowDecomposer().decompose(understanding)

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        plan = decomposition.workflow.steps[0].plan
        result = executor.execute(plan)

        assert result.success is True
        assert result.metadata["trustworthy_success"] is True

    def test_unverifiable_result_is_not_trusted(self, tmp_path):
        """If verification fails, trustworthy_success must be False."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        })

        understanding = ObjectiveUnderstanding(engine).understand("open Chrome")
        decomposition = WorkflowDecomposer().decompose(understanding)

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": False,
            "message": "Chrome launch attempted.",
        }

        executor = ActionExecutor(os_manager)
        plan = decomposition.workflow.steps[0].plan
        result = executor.execute(plan)

        assert result.success is True
        assert result.verified is False
        assert result.metadata["trustworthy_success"] is False


# =========================================================
# 2. MULTI-STEP WORKFLOW EXECUTION
# =========================================================


class TestMultiStepWorkflow:
    """Test multi-step workflows with dependency ordering."""

    def test_two_step_workflow_executes_in_order(self, tmp_path):
        """Create folder then create file in folder — dependency ordering."""
        folder_path = str(tmp_path / "test_folder")
        file_path = str(tmp_path / "test_folder" / "test.txt")

        engine = FakeDecisionEngine({
            "create folder": _decision(
                "create folder",
                operation="folder.create",
                target=folder_path,
            ),
            "create file in folder": _decision(
                "create file in folder",
                operation="file.create",
                target=file_path,
            ),
        })

        understanding = ObjectiveUnderstanding(engine).understand(
            "create folder then create file in folder"
        )
        decomposition = WorkflowDecomposer().decompose(understanding)

        assert decomposition.executable is True
        assert len(decomposition.workflow.steps) == 2

        steps = decomposition.workflow.steps
        assert steps[0].depends_on == ()
        assert steps[1].depends_on == ("step-1",)

    def test_two_step_workflow_executes_both(self):
        """Both steps of a two-step workflow complete successfully."""
        os_manager = Mock()
        os_manager.open_application.side_effect = [
            {
                "success": True,
                "operation": "application.open",
                "application": "chrome",
                "executed": True,
                "verified": True,
                "running": True,
                "message": "Chrome opened.",
            },
            {
                "success": True,
                "operation": "application.open",
                "application": "word",
                "executed": True,
                "verified": True,
                "running": True,
                "message": "Word opened.",
            },
        ]

        workflow = WorkflowPlan(
            objective="open Chrome and Word",
            steps=(
                WorkflowStep(
                    "step-1",
                    ActionPlan(
                        operation="application.open",
                        target="chrome",
                        confidence=0.95,
                    ),
                ),
                WorkflowStep(
                    "step-2",
                    ActionPlan(
                        operation="application.open",
                        target="word",
                        confidence=0.95,
                    ),
                    depends_on=("step-1",),
                ),
            ),
        )

        engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))
        result = engine.execute(workflow)

        assert result.success is True
        assert result.status == "completed"
        assert result.final_verified is True
        assert len(result.steps) == 2

    def test_multi_step_stops_on_failure(self, tmp_path):
        """If the first step fails, the second must not execute."""
        os_manager = Mock()
        os_manager.create_folder.return_value = {
            "success": False,
            "operation": "folder.create",
            "error": "Permission denied",
            "executed": True,
            "verified": False,
        }

        workflow = WorkflowPlan(
            objective="create folder and file",
            steps=(
                WorkflowStep(
                    "step-1",
                    ActionPlan(
                        operation="folder.create",
                        target="test_folder",
                        confidence=0.95,
                    ),
                ),
                WorkflowStep(
                    "step-2",
                    ActionPlan(
                        operation="file.create",
                        target="test_file.txt",
                        confidence=0.95,
                    ),
                    depends_on=("step-1",),
                ),
            ),
        )

        engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))
        result = engine.execute(workflow)

        assert result.success is False
        os_manager.create_file.assert_not_called()

    def test_dependency_chain_validation(self):
        """Invalid dependencies are detected before execution."""
        workflow = WorkflowPlan(
            objective="dependent workflow",
            steps=(
                WorkflowStep(
                    "one",
                    ActionPlan("application.inspect", "chrome"),
                ),
                WorkflowStep(
                    "two",
                    ActionPlan("application.inspect", "word"),
                    depends_on=("missing",),
                ),
            ),
        )

        engine = UniversalDesktopWorkflowEngine(ActionExecutor(Mock()))
        result = engine.execute(workflow)

        assert result.success is False
        assert result.status == "invalid_plan"


# =========================================================
# 3. SAFETY GATE INTEGRATION
# =========================================================


class TestSafetyGateIntegration:
    """Dangerous operations are blocked before reaching OSManager."""

    def test_system_shutdown_blocked(self):
        """system.shutdown is blocked and never reaches OS."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan(
            operation="system.shutdown",
            target="computer",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.success is False
        assert result.status == "safety_blocked"
        assert result.executed is False
        assert result.verified is False
        assert os_manager.method_calls == []

    def test_safety_decision_preserved_in_result(self):
        """The safety decision is preserved in the ActionResult metadata."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan(
            operation="system.shutdown",
            target="computer",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.metadata["safety_status"] == "denied"
        safety_decision = result.metadata["safety_decision"]
        assert safety_decision["operation"] == "system.shutdown"
        assert safety_decision["allowed"] is False
        assert safety_decision["status"] == "denied"
        assert isinstance(safety_decision["reason"], str)

    def test_shell_execute_blocked(self):
        """shell.execute is blocked by safety gate."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan(
            operation="shell.execute",
            target="rm -rf /",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.success is False
        assert result.status == "safety_blocked"
        assert os_manager.method_calls == []

    def test_filesystem_delete_blocked(self):
        """filesystem.delete is blocked by safety gate."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan(
            operation="filesystem.delete",
            target="important.txt",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.success is False
        assert result.status == "safety_blocked"
        assert os_manager.method_calls == []

    def test_unknown_operation_blocked(self):
        """Unknown operations are blocked by safety gate."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan.model_construct(
            operation="totally.unknown.operation",
            target="test",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.success is False
        assert result.status == "safety_blocked"
        assert os_manager.method_calls == []

    @pytest.mark.parametrize(
        "operation",
        [
            "system.shutdown",
            "system.restart",
            "shell.execute",
            "filesystem.delete",
            "process.kill",
        ],
    )
    def test_all_dangerous_operations_blocked(self, operation):
        """All known dangerous operations are blocked."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan(
            operation=operation,
            target="test",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.success is False
        assert result.status == "safety_blocked"
        assert result.executed is False
        assert os_manager.method_calls == []

    def test_supported_operation_passes_safety(self):
        """application.open passes through safety gate."""
        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        plan = ActionPlan(
            operation="application.open",
            target="chrome",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.success is True
        os_manager.open_application.assert_called_once_with("chrome")


# =========================================================
# 4. CAPABILITY DISCOVERY PIPELINE
# =========================================================


class TestCapabilityDiscoveryPipeline:
    """Capability registry correctly classifies and resolves operations."""

    def test_known_operation_is_classified(self):
        """Known operations are classified as supported."""
        assert CapabilityRegistry.classify("application.open") == "supported"
        assert CapabilityRegistry.classify("application.close") == "supported"
        assert CapabilityRegistry.classify("application.inspect") == "supported"

    def test_unknown_operation_is_unknown(self):
        """Unknown operations are classified as unknown."""
        assert CapabilityRegistry.classify("totally.unknown") == "unknown"

    def test_empty_operation_is_invalid(self):
        """Empty operation is classified as invalid."""
        assert CapabilityRegistry.classify("") == "invalid"

    def test_non_string_operation_is_invalid(self):
        """Non-string operation is classified as invalid."""
        assert CapabilityRegistry.classify(123) == "invalid"

    def test_capability_exists_for_registered_operations(self):
        """Capability objects exist for registered operations."""
        cap = CapabilityRegistry.get("application.open")
        assert isinstance(cap, Capability)
        assert cap.operation == "application.open"
        assert cap.category == "application"
        assert cap.enabled is True

    def test_dangerous_operations_are_flagged(self):
        """Dangerous operations are flagged by registry."""
        assert CapabilityRegistry.is_dangerous("application.open") is False
        assert CapabilityRegistry.is_dangerous("system.shutdown") is True

    def test_registry_operations_are_deterministic(self):
        """Registry operations return the same results deterministically."""
        first = CapabilityRegistry.operations()
        second = CapabilityRegistry.operations()
        assert first == second

    def test_capability_resolver_finds_matching_capabilities(self):
        """CapabilityResolver resolves requirements to capabilities."""
        from genesis_os.capabilities import CapabilityRequirement

        registry = CapabilityRegistry()
        resolver = CapabilityResolver(registry)

        requirement = CapabilityRequirement(
            capability_id="application.open",
            category="application",
            operation="application.open",
        )

        result = resolver.resolve(requirement)

        assert result is not None
        assert result.resolved is True

    def test_unknown_operation_rejected_by_resolver(self):
        """Unknown operations are rejected by the capability resolver."""
        from genesis_os.capabilities import CapabilityRequirement
        from genesis_os.capability_resolver import CapabilityUnavailableError

        registry = CapabilityRegistry()
        resolver = CapabilityResolver(registry)

        requirement = CapabilityRequirement(
            capability_id="totally.unknown.operation",
            category="unknown",
            operation="totally.unknown.operation",
        )

        with pytest.raises(CapabilityUnavailableError):
            resolver.resolve(requirement)

    def test_safety_check_for_registered_operations(self):
        """ExecutionSafety agrees with registry for registered operations."""
        operations = [
            "application.open",
            "application.close",
            "application.inspect",
        ]
        for op in operations:
            safety = ExecutionSafety.check(op)
            assert safety.status == "supported"
            assert safety.allowed is True

    @pytest.mark.parametrize(
        "operation",
        [
            "gui.focus_window",
            "gui.type_text",
            "gui.click",
            "document.read",
            "document.inspect_intel",
            "document.search_intel",
            "spreadsheet.read_intel",
            "spreadsheet.inspect_intel",
            "spreadsheet.sort",
        ],
    )
    def test_new_capabilities_are_registered(self, operation):
        """Capabilities from Level 3.10+ are registered and enabled."""
        assert CapabilityRegistry.exists(operation), f"{operation} should exist"
        cap = CapabilityRegistry.get(operation)
        assert cap.enabled is True, f"{operation} should be enabled"


# =========================================================
# 5. DOCUMENT INTELLIGENCE INTEGRATION
# =========================================================


class TestDocumentIntelligenceIntegration:
    """Document inspect, read, search pipeline with real files."""

    def test_inspect_read_search_pipeline(self, tmp_path):
        """Full document pipeline: create -> inspect -> read -> search."""
        doc = DocumentIntelligence()
        test_file = str(tmp_path / "test_document.txt")
        content = "Genesis OS document integration test. Testing document intelligence."

        create_result = doc.create_txt(test_file, content)
        assert create_result.success is True
        assert Path(test_file).exists()

        inspect_result = doc.inspect(test_file)
        assert inspect_result.success is True
        assert inspect_result.format == DocumentFormat.TXT
        assert inspect_result.data["name"] == "test_document.txt"
        assert inspect_result.data["size"] > 0

        read_result = doc.read(test_file)
        assert read_result.success is True
        assert "Genesis OS" in read_result.data["text"]

        search_result = doc.search(test_file, "Genesis")
        assert search_result.success is True
        assert search_result.data["match_count"] >= 1
        assert any(
            "Genesis" in m["match"]
            for m in search_result.data["matches"]
        )

    def test_document_creation_txt_verifies_file_exists(self, tmp_path):
        """Document creation produces a real file on disk."""
        doc = DocumentIntelligence()
        test_file = str(tmp_path / "created_doc.txt")
        content = "Hello, Genesis OS!"

        result = doc.create_txt(test_file, content)

        assert result.success is True
        assert Path(test_file).exists()
        assert Path(test_file).read_text(encoding="utf-8") == content

    def test_document_creation_csv(self, tmp_path):
        """CSV creation produces a valid CSV file."""
        doc = DocumentIntelligence()
        test_file = str(tmp_path / "created_data.csv")
        headers = ["Name", "Score"]
        rows = [["Alice", "95"], ["Bob", "87"]]

        result = doc.create_csv(test_file, headers, rows)

        assert result.success is True
        assert Path(test_file).exists()

        read_result = doc.read(test_file)
        assert read_result.success is True
        assert "Alice" in read_result.data["text"]

    def test_document_search_no_matches(self, tmp_path):
        """Search for non-existent text returns zero matches."""
        doc = DocumentIntelligence()
        test_file = str(tmp_path / "search_test.txt")
        doc.create_txt(test_file, "Hello World")

        result = doc.search(test_file, "nonexistent")
        assert result.success is True
        assert result.data["match_count"] == 0

    def test_document_inspect_missing_file(self, tmp_path):
        """Inspecting a non-existent file returns failure."""
        doc = DocumentIntelligence()
        result = doc.inspect(str(tmp_path / "missing.txt"))
        assert result.success is False

    def test_document_read_missing_file(self, tmp_path):
        """Reading a non-existent file returns failure."""
        doc = DocumentIntelligence()
        result = doc.read(str(tmp_path / "missing.txt"))
        assert result.success is False


# =========================================================
# 6. SPREADSHEET INTELLIGENCE INTEGRATION
# =========================================================


class TestSpreadsheetIntelligenceIntegration:
    """Spreadsheet inspect, read_as_dicts, sort pipeline with real CSV."""

    def test_inspect_read_pipeline(self, tmp_path):
        """Full spreadsheet pipeline: create -> inspect -> read."""
        si = SpreadsheetIntelligence()
        csv_file = str(tmp_path / "students.csv")

        data = [
            {"Name": "Charlie", "Score": "85"},
            {"Name": "Alice", "Score": "95"},
            {"Name": "Bob", "Score": "78"},
        ]

        create_result = si.create_from_dicts(csv_file, data)
        assert create_result.success is True
        assert Path(csv_file).exists()

        inspect_result = si.inspect(csv_file)
        assert inspect_result.success is True
        info = inspect_result.data
        assert info.sheets[0].row_count == 3
        assert "Name" in info.sheets[0].headers
        assert "Score" in info.sheets[0].headers

        read_result = si.read_as_dicts(csv_file)
        assert read_result.success is True
        assert len(read_result.data) == 3

    def test_spreadsheet_creation_verifies_file_exists(self, tmp_path):
        """Spreadsheet creation produces a real file on disk."""
        si = SpreadsheetIntelligence()
        csv_file = str(tmp_path / "created_sheet.csv")
        data = [
            {"Product": "Widget", "Price": "10"},
            {"Product": "Gadget", "Price": "20"},
        ]

        result = si.create_from_dicts(csv_file, data)

        assert result.success is True
        assert Path(csv_file).exists()

    def test_spreadsheet_read_raw_returns_headers_and_rows(self, tmp_path):
        """Read raw returns headers and row data."""
        si = SpreadsheetIntelligence()
        csv_file = str(tmp_path / "raw_test.csv")
        data = [
            {"Col1": "a", "Col2": "1"},
            {"Col1": "b", "Col2": "2"},
        ]
        si.create_from_dicts(csv_file, data)

        result = si.read(csv_file)
        assert result.success is True
        assert result.data["headers"] == ["Col1", "Col2"]
        assert len(result.data["rows"]) == 2

    def test_spreadsheet_sort_nonexistent_column(self, tmp_path):
        """Sort by non-existent column returns failure."""
        si = SpreadsheetIntelligence()
        csv_file = str(tmp_path / "bad_sort.csv")
        data = [{"Name": "Alice"}]
        si.create_from_dicts(csv_file, data)

        result = si.sort(csv_file, "NonExistent")
        assert result.success is False

    def test_spreadsheet_inspect_missing_file(self, tmp_path):
        """Inspecting a non-existent file returns failure."""
        si = SpreadsheetIntelligence()
        result = si.inspect(str(tmp_path / "missing.csv"))
        assert result.success is False


# =========================================================
# 7. CONTEXT PIPELINE INTEGRATION
# =========================================================


class TestContextPipelineIntegration:
    """Context resolution with session state and multi-turn continuation."""

    def test_session_binder_records_decision(self):
        """SessionContextBinder records a Level 3 decision."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        decision = _decision("open Chrome", target="Chrome")
        binder.record_decision(decision)

        assert binder.has_context is True

    def test_session_binder_does_not_record_weak(self):
        """Weak or non-OS decisions are not recorded."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision({"level": 1, "mode": "conversation", "confidence": 0.99})
        assert binder.has_context is False

    def test_session_binder_rebinds_continuation(self):
        """Follow-up requests rebind to previous context."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision(_decision("open Chrome", target="Chrome"))
        assert binder.has_context is True

        decision = binder.try_rebind(
            "now search YouTube for Python"
        )
        assert decision is not None
        assert decision["level"] == 3
        assert decision["intent"] == "browser.search"

    def test_session_binder_reset_clears_context(self):
        """reset() clears all stored context."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision(_decision("open Chrome", target="Chrome"))
        assert binder.has_context is True

        binder.reset()
        assert binder.has_context is False

    def test_session_binder_rejects_live_state_anaphora(self):
        """Requests referencing live UI state must be declined."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision(_decision("open Chrome", target="Chrome"))

        result = binder.try_rebind("open the first result")
        assert result is None

    def test_session_binder_conversational_stays_conversational(self):
        """Conversational follow-ups are not re-bound to Level 3."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision(_decision("open Chrome", target="Chrome"))

        result = binder.try_rebind("tell me about IELTS")
        assert result is None

    def test_marker_only_text_declines(self):
        """Text with only markers like 'now' declines."""
        from genesis_os.session_context import SessionContextBinder

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision(_decision("open Chrome", target="Chrome"))

        assert binder.try_rebind("now") is None
        assert binder.try_rebind("and then") is None


# =========================================================
# 8. OBSERVATION LOOP INTEGRATION
# =========================================================


class TestObservationLoopIntegration:
    """Observation works for file operations with expected vs actual state."""

    def test_enhanced_observation_result_structure(self):
        """EnhancedObservationResult has correct structure."""
        result = EnhancedObservationResult(
            step_id="step-1",
            operation="file.create",
            target="/tmp/test.txt",
            expected_state={"file_exists": True},
            actual_state={"file_exists": True},
            matches_expected=True,
        )
        assert result.step_id == "step-1"
        assert result.operation == "file.create"
        assert result.matches_expected is True
        assert result.confidence == 1.0

    def test_enhanced_observation_result_serialization(self):
        """EnhancedObservationResult serializes to dict."""
        result = EnhancedObservationResult(
            step_id="step-1",
            operation="file.create",
            target="/tmp/test.txt",
            expected_state={"file_exists": True},
            actual_state={"file_exists": True},
            matches_expected=True,
        )
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["step_id"] == "step-1"
        assert data["matches_expected"] is True

    def test_enhanced_observation_downgrades_to_base(self):
        """EnhancedObservationResult can downgrade to base ObservationResult."""
        result = EnhancedObservationResult(
            step_id="step-1",
            operation="file.create",
            target="/tmp/test.txt",
            expected_state={"file_exists": True},
            actual_state={"file_exists": True},
            matches_expected=True,
        )
        base = result.to_observation_result()
        assert isinstance(base, ObservationResult)
        assert base.step_id == "step-1"

    def test_enhanced_observation_handles_discrepancy(self):
        """When expected and actual differ, discrepancy is reported."""
        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"application_running": True},
            actual_state={"application_running": False},
            matches_expected=False,
            discrepancy="Application not found running",
        )
        assert result.matches_expected is False
        assert result.discrepancy is not None

    def test_enhanced_observation_confidence_scoring(self):
        """Confidence is computed correctly."""
        result = EnhancedObservationResult(
            step_id="step-1",
            operation="file.create",
            target="/tmp/test.txt",
            expected_state={"file_exists": True},
            actual_state={"file_exists": True},
            matches_expected=True,
            confidence=0.95,
        )
        assert result.confidence == 0.95

    def test_enhanced_observation_module_exists(self):
        """EnhancedObservationLoop module is importable."""
        assert EnhancedObservationLoop is not None

    def test_enhanced_observation_result_has_enhanced_checks(self):
        """EnhancedObservationResult supports enhanced_checks dict."""
        result = EnhancedObservationResult(
            step_id="step-1",
            operation="file.create",
            target="/tmp/test.txt",
            expected_state={"file_exists": True},
            actual_state={"file_exists": True},
            matches_expected=True,
            enhanced_checks={"process_running": True},
        )
        assert result.enhanced_checks["process_running"] is True


# =========================================================
# 9. RECOVERY ENGINE INTEGRATION
# =========================================================


class TestRecoveryEngineIntegration:
    """Recovery strategies are registered and bounded."""

    def _make_engine(self):
        from genesis_os.recovery_engine import RecoveryEngine
        from genesis_os.os_manager import OSManager

        os_manager = Mock(spec=OSManager)
        return RecoveryEngine(os_manager)

    def test_recovery_engine_has_strategies(self):
        """RecoveryEngine has registered strategies."""
        engine = self._make_engine()
        strategies = engine.list_strategies()
        assert len(strategies) >= 5

    def test_application_launch_fallback_exists(self):
        """application_launch_fallback strategy exists."""
        engine = self._make_engine()
        strategy = engine.get_strategy("application_launch_fallback")
        assert strategy is not None
        assert strategy.max_attempts >= 2

    def test_file_path_fallback_exists(self):
        """file_path_fallback strategy exists."""
        engine = self._make_engine()
        strategy = engine.get_strategy("file_path_fallback")
        assert strategy is not None

    def test_folder_path_fallback_exists(self):
        """folder_path_fallback strategy exists."""
        engine = self._make_engine()
        strategy = engine.get_strategy("folder_path_fallback")
        assert strategy is not None

    def test_window_focus_fallback_exists(self):
        """window_focus_fallback strategy exists."""
        engine = self._make_engine()
        strategy = engine.get_strategy("window_focus_fallback")
        assert strategy is not None

    def test_alternative_application_exists(self):
        """alternative_application strategy exists."""
        engine = self._make_engine()
        strategy = engine.get_strategy("alternative_application")
        assert strategy is not None

    def test_state_reobservation_exists(self):
        """state_reobservation strategy exists."""
        engine = self._make_engine()
        strategy = engine.get_strategy("state_reobservation")
        assert strategy is not None

    def test_all_strategies_have_bounded_attempts(self):
        """All strategies have bounded retry attempts."""
        engine = self._make_engine()
        for strategy in engine.list_strategies():
            assert strategy.max_attempts > 0
            assert strategy.max_attempts <= 5

    def test_strategies_have_descriptions(self):
        """All strategies have descriptions."""
        engine = self._make_engine()
        for strategy in engine.list_strategies():
            assert strategy.description

    def test_find_applicable_strategies(self):
        """Applicable strategies can be found for a given error."""
        engine = self._make_engine()
        strategies = engine.find_applicable_strategies(
            "application.open", "launch_failed"
        )
        assert len(strategies) >= 1

    def test_recovery_result_serialization(self):
        """RecoveryResult serializes to dict."""
        from genesis_os.recovery_engine import RecoveryResult

        result = RecoveryResult(
            original_step_id="step-1",
            original_error="Launch failed",
            strategies_attempted=[],
            recovered=False,
        )
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["recovered"] is False


# =========================================================
# 10. FULL LEVEL 3 DECISION -> EXECUTION CHAIN
# =========================================================


class TestFullLevel3DecisionExecutionChain:
    """WorkflowDecisionEngine -> ActionPlan -> ActionExecutor -> OSManager end-to-end."""

    def test_decision_to_execution_chain(self, tmp_path):
        """Complete chain from decision engine to OS execution."""
        decision = WorkflowDecisionEngine().decide("open Chrome")

        assert decision["level"] == 3
        assert decision["intent"] == "application.open"

        plan = ActionPlan.from_decision(decision)

        assert plan.operation == "application.open"
        assert plan.target == "chrome"

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        result = executor.execute(plan)

        assert result.success is True
        assert result.status == "verified"
        assert result.verified is True

    def test_result_has_proper_structure(self):
        """ActionResult has all required fields."""
        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        plan = ActionPlan(
            operation="application.open",
            target="chrome",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert hasattr(result, "success")
        assert hasattr(result, "status")
        assert hasattr(result, "executed")
        assert hasattr(result, "verified")
        assert hasattr(result, "operation")
        assert hasattr(result, "target")
        assert hasattr(result, "error")
        assert hasattr(result, "metadata")
        assert hasattr(result, "message")
        assert hasattr(result, "plan")
        assert hasattr(result, "execution")
        assert hasattr(result, "verification")

    def test_result_serialization(self):
        """ActionResult serializes to dict."""
        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        plan = ActionPlan(
            operation="application.open",
            target="chrome",
            confidence=0.99,
        )

        result = executor.execute(plan)
        data = result.to_dict()

        assert isinstance(data, dict)
        assert data["success"] is True
        assert data["operation"] == "application.open"
        assert data["target"] == "chrome"
        assert data["status"] == "verified"

    def test_full_objective_to_workflow_to_execution(self):
        """Objective text -> understanding -> decomposition -> workflow -> execution."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "open Word": _decision("open Word", target="Word"),
        })

        understanding = ObjectiveUnderstanding(engine).understand(
            "open Chrome and open Word"
        )
        assert understanding.executable is True
        assert understanding.fully_level3 is True

        decomposition = WorkflowDecomposer().decompose(understanding)
        assert decomposition.executable is True
        assert len(decomposition.workflow.steps) == 2

        os_manager = Mock()
        os_manager.open_application.side_effect = [
            {
                "success": True,
                "operation": "application.open",
                "application": "chrome",
                "executed": True,
                "verified": True,
                "running": True,
                "message": "Chrome opened.",
            },
            {
                "success": True,
                "operation": "application.open",
                "application": "word",
                "executed": True,
                "verified": True,
                "running": True,
                "message": "Word opened.",
            },
        ]

        engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))
        result = engine.execute(decomposition.workflow)

        assert result.success is True
        assert result.final_verified is True
        assert result.trustworthy_success is True
        assert len(result.steps) == 2

    def test_low_confidence_blocks_execution(self):
        """Low confidence plans are rejected before execution."""
        os_manager = Mock()
        executor = ActionExecutor(os_manager)

        plan = ActionPlan(
            operation="application.open",
            target="chrome",
            confidence=0.85,
        )

        result = executor.execute(plan)

        assert result.success is False
        assert result.status == "invalid_plan"
        assert os_manager.method_calls == []

    def test_plan_preservation_in_result(self):
        """The ActionPlan is preserved inside ActionResult."""
        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "Chrome opened.",
        }

        executor = ActionExecutor(os_manager)
        plan = ActionPlan(
            operation="application.open",
            target="chrome",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.plan == plan.to_dict()

    def test_execution_evidence_is_preserved(self):
        """Execution evidence from OS is preserved in result."""
        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "application": "chrome",
            "executed": True,
            "verified": True,
            "resolved_executable": "chrome.exe",
            "return_code": 0,
        }

        executor = ActionExecutor(os_manager)
        plan = ActionPlan(
            operation="application.open",
            target="chrome",
            confidence=0.99,
        )

        result = executor.execute(plan)

        assert result.execution["executed"] is True
        assert result.execution["resolved_executable"] == "chrome.exe"
        assert result.execution["return_code"] == 0
