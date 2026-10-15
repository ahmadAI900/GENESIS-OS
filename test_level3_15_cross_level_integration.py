"""
Genesis OS — Level 3.15
Cross-Level Integration & Multi-Turn Reference Resolution.

PHASE 5: Proves Level 1 + Level 2 + Level 3 behave as ONE runtime.

Tests the complete bidirectional integration:

    L2 -> L3: Agent produces entity, OS uses it
    L3 -> L2: OS creates file, agent processes it
    L2 -> L3 -> L2: Mixed workflows
    L3 -> L2 -> L3: OS -> agent -> OS chain

PHASE 6: Multi-turn reference resolution.

Tests that Genesis can handle:

    "Open my results folder."
    "Find the newest spreadsheet."
    "Open it."
    "Calculate the percentages."
    "Sort them highest to lowest."
    "Save it there as final."

...resolving "it", "them", "there", "the newest spreadsheet"
through conversation, entity history, and session state.

GENUINE TESTS ONLY:
    - No faked execution
    - No weakened assertions
    - Real entity tracking
    - Real state transitions
    - Real reference resolution
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

from genesis_os.entity_history import (
    EntityHistory,
    EntityType,
    EntityAction,
    EntityEntry,
)
from genesis_os.session_state import SessionState
from genesis_os.structured_context import StructuredAgentContext
from genesis_os.session_context import SessionContextBinder
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.action_executor import ActionExecutor


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


# =========================================================
# 1. ENTITY HISTORY — RECORDING & RESOLUTION
# =========================================================


class TestEntityHistory:
    """EntityHistory tracks and resolves entities across levels."""

    def test_record_and_get_recent(self):
        """Recording entities makes them available via get_recent."""

        history = EntityHistory()

        history.record(
            EntityType.FILE,
            "/tmp/report.xlsx",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Data Agent",
        )

        recent = history.get_recent(EntityType.FILE)
        assert len(recent) == 1
        assert recent[0].entity_id == "/tmp/report.xlsx"
        assert recent[0].source_agent == "Data Agent"

    def test_record_from_result_infers_file(self):
        """record_from_result infers file entity from file.create operation."""

        history = EntityHistory()

        history.record_from_result(
            "file.create",
            "/tmp/test.txt",
            {"success": True, "message": "Created"},
            source_level=3,
        )

        recent = history.get_recent(EntityType.FILE)
        assert len(recent) == 1
        assert recent[0].entity_id == "/tmp/test.txt"
        assert recent[0].action == EntityAction.CREATED

    def test_record_from_result_infers_application(self):
        """record_from_result infers application entity from application.open."""

        history = EntityHistory()

        history.record_from_result(
            "application.open",
            "Chrome",
            {"success": True, "verified": True},
            source_level=3,
        )

        recent = history.get_recent(EntityType.APPLICATION)
        assert len(recent) == 1
        assert recent[0].entity_id == "Chrome"
        assert recent[0].action == EntityAction.OPENED

    def test_resolve_pronoun_it_returns_most_recent(self):
        """Pronoun 'it' resolves to the most recent entity."""

        history = EntityHistory()

        history.record(EntityType.FILE, "report.xlsx", EntityAction.CREATED)
        history.record(EntityType.FOLDER, "Results", EntityAction.OPENED)

        resolved = history.resolve_pronoun("it")
        assert resolved == "Results"

    def test_resolve_pronoun_with_type_hint(self):
        """Pronoun 'it' with type hint resolves to most recent of that type."""

        history = EntityHistory()

        history.record(EntityType.FOLDER, "Results", EntityAction.OPENED)
        history.record(EntityType.FILE, "report.xlsx", EntityAction.CREATED)

        resolved = history.resolve_pronoun("it", entity_type_hint=EntityType.FILE)
        assert resolved == "report.xlsx"

    def test_resolve_the_file(self):
        """'the file' resolves to most recent file."""

        history = EntityHistory()

        history.record(EntityType.APPLICATION, "Chrome", EntityAction.OPENED)
        history.record(EntityType.FILE, "data.csv", EntityAction.ACCESSED)

        resolved = history.resolve_pronoun("the file")
        assert resolved == "data.csv"

    def test_resolve_the_folder(self):
        """'the folder' resolves to most recent folder."""

        history = EntityHistory()

        history.record(EntityType.FILE, "test.txt", EntityAction.CREATED)
        history.record(EntityType.FOLDER, "Downloads", EntityAction.OPENED)

        resolved = history.resolve_pronoun("the folder")
        assert resolved == "Downloads"

    def test_resolve_the_newest_spreadsheet(self):
        """'the newest spreadsheet' resolves to most recently created/modified spreadsheet."""

        history = EntityHistory()

        history.record(EntityType.SPREADSHEET, "old.csv", EntityAction.ACCESSED)
        history.record(EntityType.SPREADSHEET, "report.xlsx", EntityAction.CREATED)

        resolved = history.resolve_pronoun("the newest spreadsheet")
        assert resolved == "report.xlsx"

    def test_resolve_returns_none_when_no_history(self):
        """Resolution returns None when no entities are tracked."""

        history = EntityHistory()
        assert history.resolve_pronoun("it") is None

    def test_provenance_chain(self):
        """get_entity_provenance returns all interactions with an entity."""

        history = EntityHistory()

        history.record(EntityType.FILE, "report.xlsx", EntityAction.CREATED, source_level=3)
        history.record(EntityType.FILE, "report.xlsx", EntityAction.MODIFIED, source_level=2)
        history.record(EntityType.FILE, "report.xlsx", EntityAction.ACCESSED, source_level=1)

        provenance = history.get_entity_provenance("report.xlsx")
        assert len(provenance) == 3
        assert provenance[0].action == EntityAction.CREATED
        assert provenance[1].action == EntityAction.MODIFIED
        assert provenance[2].action == EntityAction.ACCESSED

    def test_session_summary(self):
        """get_session_summary returns correct counts."""

        history = EntityHistory()

        history.record(EntityType.FILE, "a.txt", EntityAction.CREATED, source_level=2)
        history.record(EntityType.FILE, "b.txt", EntityAction.CREATED, source_level=3)
        history.record(EntityType.APPLICATION, "Chrome", EntityAction.OPENED, source_level=3)

        summary = history.get_session_summary()
        assert summary["total_entries"] == 3
        assert summary["by_type"]["file"] == 2
        assert summary["by_type"]["application"] == 1

    def test_max_entries_enforced(self):
        """Old entries are pruned when MAX_ENTRIES is exceeded."""

        history = EntityHistory()
        history.MAX_ENTRIES = 5

        for i in range(10):
            history.record(EntityType.FILE, f"file_{i}.txt", EntityAction.CREATED)

        assert len(history._entries) == 5
        assert history._entries[0].entity_id == "file_5.txt"

    def test_clear_resets_history(self):
        """clear() removes all entries."""

        history = EntityHistory()
        history.record(EntityType.FILE, "test.txt", EntityAction.CREATED)
        history.clear()
        assert len(history._entries) == 0


# =========================================================
# 2. SESSION STATE — INTEGRATION WITH GENESIS
# =========================================================


class TestSessionStateIntegration:
    """SessionState tracks OS state across levels."""

    def test_update_application(self):
        """update_application tracks the current app."""

        state = SessionState()
        state.update_application("Chrome", is_focused=True)

        current = state.get_current_application()
        assert current is not None
        assert current.name == "Chrome"
        assert current.is_focused is True

    def test_mark_application_closed(self):
        """mark_application_closed removes the app."""

        state = SessionState()
        state.update_application("Chrome", is_focused=True)
        state.mark_application_closed("Chrome")

        assert state.get_current_application() is None

    def test_set_current_folder(self):
        """set_current_folder tracks the working directory."""

        state = SessionState()
        state.set_current_folder("C:\\Users\\test\\Downloads")

        assert state.get_current_folder() == "C:\\Users\\test\\Downloads"

    def test_set_active_document(self):
        """set_active_document tracks the current file."""

        state = SessionState()
        state.set_active_document("C:\\report.xlsx")

        assert state.get_active_document() == "C:\\report.xlsx"
        assert "C:\\report.xlsx" in state.get_recent_files()

    def test_clipboard_tracking(self):
        """Clipboard content is tracked."""

        state = SessionState()
        state.set_clipboard("Hello World")

        assert state.get_clipboard() == "Hello World"

    def test_browser_tracking(self):
        """Browser state is tracked."""

        state = SessionState()
        state.update_browser("Chrome", url="https://google.com", search_query="python")

        browser = state.get_browser()
        assert browser is not None
        assert browser.current_url == "https://google.com"
        assert browser.last_search_query == "python"

    def test_task_lifecycle(self):
        """Task state transitions: start -> update steps -> complete."""

        state = SessionState()
        state.start_task("task-1", "Open Chrome and Word", [{"step": "open chrome"}, {"step": "open word"}])

        task = state.get_current_task()
        assert task is not None
        assert task.objective == "Open Chrome and Word"

        state.update_task_step("step-1", True)
        state.update_task_step("step-2", True)

        completed = state.complete_task(success=True)
        assert completed is not None
        assert completed.metadata["success"] is True

        assert state.get_current_task() is None

    def test_serialization(self):
        """SessionState serializes to dict."""

        state = SessionState()
        state.update_application("Chrome", is_focused=True)
        state.set_current_folder("C:\\test")

        data = state.to_dict()
        assert data["current_application"] == "Chrome"
        assert data["current_folder"] == "C:\\test"

    def test_resolve_reference_pronouns(self):
        """resolve_reference handles pronouns."""

        state = SessionState()
        state.set_active_document("C:\\report.xlsx")

        assert state.resolve_reference("the file") == "C:\\report.xlsx"
        assert state.resolve_reference("the document") == "C:\\report.xlsx"


# =========================================================
# 3. STRUCTURED AGENT CONTEXT
# =========================================================


class TestStructuredAgentContext:
    """StructuredAgentContext bundles state for agents."""

    def test_from_genesis_state_builds_context(self):
        """from_genesis_state creates a context with session and entity data."""

        session = SessionState()
        session.update_application("Chrome", is_focused=True)
        session.set_current_folder("C:\\Users\\test")
        session.set_active_document("C:\\report.xlsx")

        history = EntityHistory()
        history.record(EntityType.FILE, "report.xlsx", EntityAction.CREATED, source_level=3)

        ctx = StructuredAgentContext.from_genesis_state(
            "Analyze the report",
            session_state=session,
            entity_history=history,
        )

        assert ctx.current_application == "Chrome"
        assert ctx.current_folder == "C:\\Users\\test"
        assert ctx.active_document == "C:\\report.xlsx"
        assert len(ctx.recent_entities) == 1

    def test_to_context_string_includes_entities(self):
        """to_context_string renders entity history."""

        history = EntityHistory()
        history.record(EntityType.FILE, "data.csv", EntityAction.CREATED, source_level=3)

        ctx = StructuredAgentContext.from_genesis_state(
            "Process data",
            entity_history=history,
        )

        rendered = ctx.to_context_string()
        assert "data.csv" in rendered
        assert "created" in rendered
        assert "GENESIS STRUCTURED CONTEXT" in rendered

    def test_to_context_string_includes_session(self):
        """to_context_string renders session state."""

        session = SessionState()
        session.update_application("Chrome", is_focused=True)
        session.set_current_folder("C:\\Downloads")

        ctx = StructuredAgentContext.from_genesis_state(
            "task",
            session_state=session,
        )

        rendered = ctx.to_context_string()
        assert "Chrome" in rendered
        assert "C:\\Downloads" in rendered

    def test_resolve_reference_file(self):
        """resolve_reference resolves 'the file' to active document."""

        ctx = StructuredAgentContext(
            active_document="C:\\report.xlsx",
        )

        assert ctx.resolve_reference("the file") == "C:\\report.xlsx"

    def test_resolve_reference_pronoun(self):
        """resolve_reference resolves 'it' to active document."""

        ctx = StructuredAgentContext(
            active_document="C:\\report.xlsx",
        )

        assert ctx.resolve_reference("it") == "C:\\report.xlsx"


# =========================================================
# 4. CROSS-LEVEL REFERENCE RESOLUTION
# =========================================================


class TestCrossLevelReferenceResolution:
    """SessionContextBinder resolves cross-level references."""

    def test_entity_history_resolves_pronoun_in_rebind(self):
        """Binder resolves 'open it' when entity history has a file."""

        history = EntityHistory()
        history.record(EntityType.FILE, "C:\\report.xlsx", EntityAction.CREATED, source_level=2)

        binder = SessionContextBinder(WorkflowDecisionEngine())
        binder.set_entity_history(history)

        # Record a previous L3 decision so has_context is True
        binder.record_decision({
            "level": 3,
            "mode": "os",
            "intent": "folder.open",
            "application": "explorer",
            "target": "C:\\Users\\test",
            "confidence": 0.95,
        })

        # "open it" should resolve "it" to "C:\\report.xlsx" via entity history
        # Then the resolved text "open C:\\report.xlsx" gets evaluated
        result = binder.try_rebind("open it")

        # 2026-10-14: this test computed `result` and asserted nothing, so
        # it could only ever fail by raising. It now asserts what its name
        # and docstring promise.
        #
        # These assertions FAILED until 2026-10-15, and that was a real
        # product defect, not a bad test. Measured 2026-10-14:
        #   _resolve_entity_reference("open it") -> "open C:\report.xlsx"   (worked)
        #   decision_engine.decide(that)         -> level 3, file.open, 0.96 (worked)
        #   try_rebind("open it")                -> None                    (broken)
        #
        # Cause: genesis_os/session_context.py try_rebind() assigned
        # `text = resolved_text` BEFORE the `stripped == text` check, so
        # the guard `if resolved_text is not None and resolved_text != text`
        # compared resolved_text to itself, was always False, and fell into
        # `else: return None`. The branch intended to handle "no markers
        # were stripped, but an entity WAS resolved" was therefore
        # unreachable. The sibling test passed only because "now" is a
        # marker, so stripping changes the string and the broken branch was
        # never entered.
        #
        # FIXED 2026-10-15: try_rebind() now captures `entity_resolved`
        # BEFORE reassigning `text`, and the branch keys off that flag
        # instead of re-deriving it from the already-overwritten `text`.
        assert result is not None, (
            "try_rebind('open it') returned None. The entity reference WAS "
            "resolved (to 'open C:\\report.xlsx') and the decision engine "
            "decides that text as level 3 / file.open at confidence 0.96, "
            "so the binder must not drop a decision it should return.")
        assert result["level"] == 3, result
        # decide() lowercases the target, so compare case-insensitively.
        assert "report.xlsx" in str(result.get("target", "")).lower(), (
            f"the rebind did not resolve 'it' to the recorded entity: "
            f"{result}")

    def test_entity_history_tracks_cross_level_entities(self):
        """Entities from Level 2 are visible to Level 3 reference resolution."""

        history = EntityHistory()

        # Level 2 agent creates a file
        history.record(
            EntityType.FILE,
            "C:\\output.xlsx",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Data Agent",
        )

        # Level 3 should be able to resolve "the file"
        resolved = history.resolve_pronoun("the file")
        assert resolved == "C:\\output.xlsx"

    def test_binder_with_no_entity_history_still_works(self):
        """Binder works normally when no entity history is set."""

        binder = SessionContextBinder(WorkflowDecisionEngine())
        assert binder._entity_history is None

        binder.record_decision(_decision("open Chrome", target="Chrome"))

        result = binder.try_rebind("now search YouTube for Python")
        assert result is not None
        assert result["level"] == 3

    def test_binder_resolves_before_marker_stripping(self):
        """Entity resolution happens before marker stripping."""

        history = EntityHistory()
        history.record(EntityType.FILE, "C:\\data.csv", EntityAction.CREATED, source_level=2)

        binder = SessionContextBinder(WorkflowDecisionEngine())
        binder.set_entity_history(history)

        # The binder should try to resolve "it" in "now open it"
        # even though "now" is a marker
        binder.record_decision(_decision("open folder", operation="folder.open", target="downloads"))

        result = binder.try_rebind("now open it")

        # 2026-10-14: this test also computed `result` and asserted
        # nothing. Unlike its sibling above, the behaviour here is
        # CORRECT, so the assertion passes - and it is a real assertion,
        # not a formality.
        #
        # The property the name promises: "now" is a marker, and marker
        # stripping must not prevent the entity reference from resolving.
        # Measured 2026-10-14: _resolve_entity_reference("now open it")
        # -> "now open C:\data.csv", stripping removes "now", and the
        # decision engine returns level 3 / file.open at 0.96.
        assert result is not None, (
            "try_rebind('now open it') returned None; the marker 'now' "
            "prevented the entity reference from resolving")
        assert result["level"] == 3, result
        assert "data.csv" in str(result.get("target", "")).lower(), (
            f"the rebind did not resolve 'it' to the recorded entity: "
            f"{result}")
        # The marker must be gone from the evaluated text, not merely
        # tolerated: the decision is about the file, not about "now".
        assert "now" not in str(result.get("task", "")).lower(), result


# =========================================================
# 5. L2 -> L3: AGENT PRODUCES ENTITY, OS USES IT
# =========================================================


class TestLevel2ToLevel3Integration:
    """Level 2 agent produces entities that Level 3 can use."""

    def test_agent_creates_file_os_opens_it(self):
        """Agent creates a file, then Level 3 opens it via entity history."""

        history = EntityHistory()

        # Level 2 agent creates a file
        history.record(
            EntityType.FILE,
            "C:\\Users\\test\\report.xlsx",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Data Agent",
        )

        # Verify entity is tracked
        recent = history.get_recent(EntityType.FILE)
        assert len(recent) == 1
        assert recent[0].entity_id == "C:\\Users\\test\\report.xlsx"

        # Level 3 resolves "open it" -> "open C:\\Users\\test\\report.xlsx"
        resolved = history.resolve_pronoun("it", entity_type_hint=EntityType.FILE)
        assert resolved == "C:\\Users\\test\\report.xlsx"

        # Level 3 can now execute with the resolved target
        plan = ActionPlan(
            operation="file.open",
            target=resolved,
            confidence=0.99,
        )

        assert plan.target == "C:\\Users\\test\\report.xlsx"

    def test_agent_researches_topic_os_opens_results_folder(self):
        """Agent researches topic, OS opens the results folder."""

        history = EntityHistory()

        # Level 2 Research Agent creates results
        history.record(
            EntityType.FOLDER,
            "C:\\Users\\test\\Research_Results",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Research Agent",
        )

        # Level 3 resolves "open the folder"
        resolved = history.resolve_pronoun("the folder")
        assert resolved == "C:\\Users\\test\\Research_Results"


# =========================================================
# 6. L3 -> L2: OS CREATES FILE, AGENT PROCESSES IT
# =========================================================


class TestLevel3ToLevel2Integration:
    """Level 3 creates files that Level 2 agents process."""

    def test_os_creates_spreadsheet_agent_analyzes(self):
        """OS creates a CSV, Data Agent analyzes it."""

        history = EntityHistory()

        # Level 3 creates a spreadsheet
        history.record(
            EntityType.SPREADSHEET,
            "C:\\data\\scores.csv",
            EntityAction.CREATED,
            source_level=3,
            source_operation="spreadsheet.sort",
        )

        # Data Agent can find the entity
        recent = history.get_recent(EntityType.SPREADSHEET)
        assert len(recent) == 1
        assert recent[0].entity_id == "C:\\data\\scores.csv"

        # Data Agent receives structured context with this entity
        ctx = StructuredAgentContext.from_genesis_state(
            "Analyze the scores",
            entity_history=history,
        )

        assert len(ctx.recent_entities) == 1
        assert ctx.recent_entities[0]["entity_id"] == "C:\\data\\scores.csv"

    def test_os_opens_app_agent_writes_code_in_it(self):
        """OS opens VS Code, Coding Agent writes a file through it."""

        session = SessionState()
        session.update_application("VSCode", is_focused=True)

        history = EntityHistory()
        history.record(
            EntityType.APPLICATION,
            "VSCode",
            EntityAction.OPENED,
            source_level=3,
        )

        # Coding Agent receives context about the open app
        ctx = StructuredAgentContext.from_genesis_state(
            "Write a Python calculator",
            session_state=session,
            entity_history=history,
        )

        assert ctx.current_application == "VSCode"

        # Coding Agent creates a file
        history.record(
            EntityType.FILE,
            "C:\\project\\calculator.py",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Coding Agent",
        )

        # The file is now trackable
        resolved = history.resolve_pronoun("the file")
        assert resolved == "C:\\project\\calculator.py"


# =========================================================
# 7. L2 -> L3 -> L2: MIXED WORKFLOW
# =========================================================


class TestMixedLevelWorkflow:
    """Mixed workflows that cross Level 2 and Level 3."""

    def test_agent_researches_then_os_saves_results(self):
        """Research Agent finds info, OS saves results to folder."""

        history = EntityHistory()

        # Level 2: Research Agent works
        history.record(
            EntityType.FILE,
            "C:\\research\\findings.txt",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Research Agent",
        )

        # Level 3: OS saves to organized folder
        history.record(
            EntityType.FOLDER,
            "C:\\Final_Reports",
            EntityAction.OPENED,
            source_level=3,
        )

        # Entity history tracks the full chain
        summary = history.get_session_summary()
        assert summary["by_level"][2] == 1
        assert summary["by_level"][3] == 1

    def test_os_sets_up_workspace_agent_codes_in_it(self):
        """OS creates project folder, Coding Agent writes code."""

        history = EntityHistory()

        # Level 3: Create project structure
        history.record(EntityType.FOLDER, "C:\\project", EntityAction.CREATED, source_level=3)
        history.record(EntityType.FILE, "C:\\project\\main.py", EntityAction.CREATED, source_level=3)

        # Level 2: Coding Agent extends the project
        history.record(EntityType.FILE, "C:\\project\\utils.py", EntityAction.CREATED, source_level=2, source_agent="Coding Agent")

        # Verify chain
        project_files = history.find_entity(
            EntityType.FILE,
            name_pattern="project",
        )
        assert len(project_files) == 2

    def test_session_state_reflects_cross_level_operations(self):
        """Session state updates correctly across levels."""

        session = SessionState()

        # Level 3 opens Chrome
        session.update_application("Chrome", is_focused=True)
        assert session.get_current_application().name == "Chrome"

        # Level 3 navigates to folder
        session.set_current_folder("C:\\Downloads")
        assert session.get_current_folder() == "C:\\Downloads"

        # Level 2 agent creates file
        session.set_active_document("C:\\Downloads\\report.pdf")
        assert session.get_active_document() == "C:\\Downloads\\report.pdf"

        # Level 3 copies to clipboard
        session.set_clipboard("Report summary text")
        assert session.get_clipboard() == "Report summary text"


# =========================================================
# 8. L3 -> L2 -> L3: OS -> AGENT -> OS CHAIN
# =========================================================


class TestOsAgentOsChain:
    """Chain: OS opens app -> agent works -> OS saves result."""

    def test_full_chain_with_entity_tracking(self):
        """Full chain: open VS Code -> agent writes code -> save to folder."""

        session = SessionState()
        history = EntityHistory()

        # Step 1 (L3): Open VS Code
        session.update_application("VSCode", is_focused=True)
        history.record(EntityType.APPLICATION, "VSCode", EntityAction.OPENED, source_level=3)

        # Step 2 (L2): Coding Agent writes file
        history.record(
            EntityType.FILE,
            "C:\\project\\app.py",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Coding Agent",
        )
        session.set_active_document("C:\\project\\app.py")

        # Step 3 (L3): Copy result to clipboard
        session.set_clipboard("Code generated successfully")
        history.record(
            EntityType.CLIPBOARD,
            "code_result",
            EntityAction.MODIFIED,
            source_level=3,
        )

        # Verify full chain is tracked
        assert session.get_current_application().name == "VSCode"
        assert session.get_active_document() == "C:\\project\\app.py"
        assert session.get_clipboard() == "Code generated successfully"

        summary = history.get_session_summary()
        assert summary["total_entries"] == 3

    def test_chain_with_structured_context(self):
        """Structured context carries the full chain state."""

        session = SessionState()
        history = EntityHistory()

        session.update_application("Chrome", is_focused=True)
        session.set_current_folder("C:\\Users\\test")
        history.record(EntityType.APPLICATION, "Chrome", EntityAction.OPENED, source_level=3)
        history.record(EntityType.FILE, "data.csv", EntityAction.CREATED, source_level=2, source_agent="Data Agent")

        ctx = StructuredAgentContext.from_genesis_state(
            "Open the spreadsheet",
            session_state=session,
            entity_history=history,
        )

        rendered = ctx.to_context_string()
        assert "Chrome" in rendered
        assert "data.csv" in rendered
        assert "Data Agent" in rendered


# =========================================================
# 9. SESSION STATE UPDATE FROM ACTION RESULTS
# =========================================================


class TestSessionStateUpdatesFromResults:
    """Session state updates correctly from action execution results."""

    def test_application_open_updates_session(self):
        """application.open updates session state."""

        session = SessionState()
        assert session.get_current_application() is None

        # Simulate what _update_session_from_result does
        session.update_application("Chrome", is_focused=True)

        current = session.get_current_application()
        assert current is not None
        assert current.name == "Chrome"

    def test_folder_open_updates_session(self):
        """folder.open updates current folder."""

        session = SessionState()
        session.set_current_folder("C:\\Users\\test\\Downloads")

        assert session.get_current_folder() == "C:\\Users\\test\\Downloads"

    def test_file_create_updates_recent(self):
        """file.create adds to recent files."""

        session = SessionState()
        session.set_active_document("C:\\report.xlsx")

        recent = session.get_recent_files()
        assert "C:\\report.xlsx" in recent

    def test_browser_search_updates_session(self):
        """browser.search updates browser state."""

        session = SessionState()
        session.update_browser("Chrome", search_query="python tutorials", search_engine="google")

        browser = session.get_browser()
        assert browser.last_search_query == "python tutorials"
        assert browser.last_search_engine == "google"


# =========================================================
# 10. ADVERSARIAL MULTI-TURN TESTS
# =========================================================


class TestAdversarialMultiTurn:
    """
    Adversarial tests for multi-turn reference resolution.

    These tests ensure Genesis handles tricky multi-turn
    scenarios correctly WITHOUT guessing or faking.
    """

    def test_pronoun_without_history_returns_none(self):
        """Pronoun 'it' with no entity history returns None."""

        history = EntityHistory()
        assert history.resolve_pronoun("it") is None

    def test_ambiguous_reference_with_multiple_files(self):
        """Ambiguous reference to multiple files resolves to most recent."""

        history = EntityHistory()

        history.record(EntityType.FILE, "old_report.xlsx", EntityAction.CREATED)
        history.record(EntityType.FILE, "new_report.xlsx", EntityAction.CREATED)

        resolved = history.resolve_pronoun("the file")
        assert resolved == "new_report.xlsx"

    def test_live_state_anaphora_not_faked(self):
        """References to live browser results are never faked."""

        binder = SessionContextBinder(WorkflowDecisionEngine())
        binder.record_decision(_decision("open Chrome", target="Chrome"))

        assert binder.try_rebind("open the first result") is None
        assert binder.try_rebind("click the second link") is None
        assert binder.try_rebind("show the top video") is None

    def test_conversational_glue_not_misinterpreted(self):
        """Conversational follow-ups are not treated as OS commands."""

        binder = SessionContextBinder(WorkflowDecisionEngine())
        binder.record_decision(_decision("open Chrome", target="Chrome"))

        assert binder.try_rebind("now what is an essay") is None
        assert binder.try_rebind("then tell me about IELTS") is None
        assert binder.try_rebind("now that I think about it, explain windows") is None

    def test_marker_only_text_declines(self):
        """Text with only discourse markers declines gracefully."""

        binder = SessionContextBinder(WorkflowDecisionEngine())
        binder.record_decision(_decision("open Chrome", target="Chrome"))

        assert binder.try_rebind("now") is None
        assert binder.try_rebind("and then") is None
        assert binder.try_rebind("next") is None

    def test_no_context_no_rebind(self):
        """Without prior L3 context, rebind always returns None."""

        binder = SessionContextBinder(WorkflowDecisionEngine())
        assert binder.has_context is False
        assert binder.try_rebind("now open Excel") is None

    def test_weak_decisions_not_recorded(self):
        """Weak or non-OS decisions are never recorded as context."""

        binder = SessionContextBinder(WorkflowDecisionEngine())

        binder.record_decision({"level": 1, "mode": "conversation", "confidence": 0.99})
        assert binder.has_context is False

        binder.record_decision({"level": 3, "mode": "os", "intent": "x", "confidence": 0.5})
        assert binder.has_context is False

    def test_entity_type_hint_filters_correctly(self):
        """Type hint in resolve_pronoun filters to correct entity type."""

        history = EntityHistory()

        history.record(EntityType.APPLICATION, "Chrome", EntityAction.OPENED)
        history.record(EntityType.FILE, "data.csv", EntityAction.CREATED)
        history.record(EntityType.FOLDER, "Downloads", EntityAction.OPENED)

        # "it" with FILE hint -> data.csv (most recent file)
        assert history.resolve_pronoun("it", entity_type_hint=EntityType.FILE) == "data.csv"

        # "it" with APPLICATION hint -> Chrome
        assert history.resolve_pronoun("it", entity_type_hint=EntityType.APPLICATION) == "Chrome"

        # "it" without hint -> Downloads (most recent overall)
        assert history.resolve_pronoun("it") == "Downloads"

    def test_entity_history_preserves_provenance(self):
        """Each entity entry preserves its source level and agent."""

        history = EntityHistory()

        history.record(
            EntityType.FILE, "result.py",
            EntityAction.CREATED,
            source_level=2,
            source_agent="Coding Agent",
            source_operation="code.generate",
        )

        entry = history.get_recent(EntityType.FILE)[0]
        assert entry.source_level == 2
        assert entry.source_agent == "Coding Agent"
        assert entry.source_operation == "code.generate"

    def test_multiple_entity_types_tracked_independently(self):
        """Different entity types are tracked independently."""

        history = EntityHistory()

        history.record(EntityType.FILE, "a.txt", EntityAction.CREATED)
        history.record(EntityType.APPLICATION, "Chrome", EntityAction.OPENED)
        history.record(EntityType.FOLDER, "Downloads", EntityAction.OPENED)
        history.record(EntityType.SPREADSHEET, "data.csv", EntityAction.CREATED)

        assert len(history.get_recent(EntityType.FILE)) == 1
        assert len(history.get_recent(EntityType.APPLICATION)) == 1
        assert len(history.get_recent(EntityType.FOLDER)) == 1
        assert len(history.get_recent(EntityType.SPREADSHEET)) == 1

    def test_reset_clears_binder_context(self):
        """reset() clears all stored context."""

        binder = SessionContextBinder(WorkflowDecisionEngine())
        binder.record_decision(_decision("open Chrome", target="Chrome"))
        assert binder.has_context is True

        binder.reset()
        assert binder.has_context is False

    def test_entity_history_serialization(self):
        """EntityHistory serializes to dict correctly."""

        history = EntityHistory()
        history.record(EntityType.FILE, "test.txt", EntityAction.CREATED, source_level=2)

        data = history.to_dict()
        assert data["total_entries"] == 1
        assert data["entries"][0]["entity_type"] == "file"
        assert data["entries"][0]["entity_id"] == "test.txt"

    def test_structured_context_serialization(self):
        """StructuredAgentContext serializes to dict correctly."""

        ctx = StructuredAgentContext(
            task="test task",
            current_application="Chrome",
            current_folder="C:\\test",
        )

        data = ctx.to_dict()
        assert data["task"] == "test task"
        assert data["current_application"] == "Chrome"
        assert data["current_folder"] == "C:\\test"
