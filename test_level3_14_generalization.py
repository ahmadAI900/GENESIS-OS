"""
Genesis OS — Level 3.14
Generalization Benchmark.

Tests that Genesis can understand tasks developers never explicitly programmed,
and that many different natural-language phrasings of the same task converge to
the same correct intent and capability selection.

This tests the ARCHITECTURE — not just string matching.

Test groups:
    1. Semantic Intent Convergence — same meaning, different words
    2. False Positive Protection — conversational text must NOT trigger OS
    3. Entity Understanding — different entity references resolve identically
    4. Constraint Understanding — different constraint phrasings map to same semantics
    5. Capability Registry Coverage — new capabilities exist and are registered
    6. Compound Task Detection — multi-step objectives decompose correctly
    7. Mixed Level Routing — Level 2 + Level 3 in one request
    8. Recovery Strategy Tests — recovery strategies exist and apply
    9. Session State Tests — multi-turn continuation works
   10. Observation Loop Coverage — enhanced observation covers all categories
"""

import pytest
from unittest.mock import Mock, MagicMock

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.objective_understanding import (
    ObjectiveUnderstanding,
    ObjectiveStepIntent,
    ObjectiveUnderstandingResult,
)
from genesis_os.workflow_decomposer import (
    WorkflowDecomposer,
    DecompositionResult,
)
from genesis_os.capability_registry import (
    Capability,
    CapabilityRegistry,
)
from genesis_os.execution_safety import ExecutionSafety


# =========================================================
# HELPERS
# =========================================================


def _engine():
    return WorkflowDecisionEngine()


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
    """Engine that returns pre-programmed decisions per fragment.

    Supports exact match and substring fallback so that the
    ObjectiveUnderstanding splitter can pass fragments that
    don't exactly match the pre-programmed keys.
    """

    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def decide(self, text):
        self.calls.append(text)
        if text in self.decisions:
            return self.decisions[text]
        # Substring fallback: check if any key is contained in text
        for key, decision in self.decisions.items():
            if key in text or text in key:
                return decision
        # Return a Level 1 fallback so tests don't crash
        return {
            "level": 1,
            "mode": "conversation",
            "task": text,
            "confidence": 0.5,
        }


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
        requires_clarification=any(i.requires_clarification for i in intents),
    )


# =========================================================
# 1. SEMANTIC INTENT CONVERGENCE
#    Same meaning, different words → same routing
# =========================================================


class TestSemanticIntentConvergence:
    """Different phrasings of the same task should converge to the same intent."""

    @pytest.mark.parametrize("text", [
        "Open Chrome",
        "Start Chrome up",
        "please open chrome",
        "could you launch google chrome",
        "fire up chrome",
    ])
    def test_browser_open_converges_to_level3(self, text):
        decision = _engine().decide(text)
        assert decision["level"] == 3, f"'{text}' should route to Level 3"
        assert decision["intent"] == "application.open", \
            f"'{text}' should have application.open intent"

    def test_open_chrome_and_start_chrome_resolve_same_app(self):
        """Different phrasings should resolve to the same canonical application."""
        d1 = _engine().decide("Open Chrome")
        d2 = _engine().decide("Start Chrome up")
        assert d1["level"] == d2["level"] == 3
        assert d1["application"] == d2["application"]

    @pytest.mark.parametrize("text", [
        "Find my latest report",
        "Locate the newest report",
        "Show me the most recent report",
        "search for my report",
        "find the report",
    ])
    def test_find_report_converges_to_filesearch(self, text):
        decision = _engine().decide(text)
        assert decision["level"] == 3, f"'{text}' should route to Level 3"
        intent = decision.get("intent") or decision.get("operation", "")
        assert "file" in intent, \
            f"'{text}' should resolve to a file-search intent, got {intent}"

    def test_move_files_keyword_converges_to_level3(self):
        """'move files to Reports' should route to Level 3."""
        decision = _engine().decide("move files to Reports")
        assert decision["level"] == 3

    @pytest.mark.parametrize("text", [
        "find my latest report",
        "locate the newest report",
        "show me the most recent report",
    ])
    def test_search_variants_all_route_to_level3(self, text):
        decision = _engine().decide(text)
        assert decision["level"] == 3, f"'{text}' should route to Level 3"

    def test_all_browser_variants_resolve_same_application(self):
        """All phrasings that include 'chrome' should resolve Chrome."""
        variants = [
            "Open Chrome",
            "Launch Google Chrome",
            "Start Chrome up",
        ]
        apps = set()
        for text in variants:
            decision = _engine().decide(text)
            if decision["application"]:
                apps.add(decision["application"].lower())
        assert "chrome" in apps, f"Expected 'chrome' in resolved applications, got {apps}"

    def test_open_vs_launch_vs_start_converge(self):
        """open, launch, start are synonyms for application opening."""
        texts = ["open notepad", "launch notepad", "start notepad"]
        intents = []
        for text in texts:
            decision = _engine().decide(text)
            intents.append(decision["intent"])
        assert all(i == "application.open" for i in intents), \
            f"All should converge to application.open, got {intents}"

    def test_close_vs_quit_vs_exit_converge(self):
        """close, quit, exit are synonyms for application closing."""
        texts = ["close notepad", "quit notepad", "exit notepad"]
        intents = []
        for text in texts:
            decision = _engine().decide(text)
            intents.append(decision["intent"])
        assert all(i == "application.close" for i in intents), \
            f"All should converge to application.close, got {intents}"

    def test_find_report_variants_all_have_file_search_intent(self):
        """Multiple find/report phrasings should all have file.search-like intent."""
        texts = [
            "find my latest report",
            "locate the newest report",
            "search for my report",
        ]
        for text in texts:
            decision = _engine().decide(text)
            assert decision["level"] == 3
            intent = decision.get("intent") or decision.get("operation", "")
            assert "file" in intent or "search" in intent, \
                f"'{text}' should have file/search intent, got {intent}"


# =========================================================
# 2. FALSE POSITIVE PROTECTION
#    Conversational text must NOT trigger OS execution
# =========================================================


class TestFalsePositiveProtection:
    """Conversational, educational, and linguistic text must never become Level 3."""

    @pytest.mark.parametrize("text", [
        "Is this IELTS sentence correct?",
        "What is Chrome?",
        "How does Excel work?",
        "Write a sentence about Windows.",
        "Explain what an operating system is.",
        "Tell me about Python.",
        "What does the word 'browser' mean?",
    ])
    def test_conversational_text_is_not_level3(self, text):
        decision = _engine().decide(text)
        assert decision["level"] != 3, f"'{text}' should NOT route to Level 3"

    def test_write_code_about_chrome_is_not_level3(self):
        """Writing code that mentions an app name is not Level 3."""
        decision = _engine().decide("Write Python code that opens Chrome")
        assert decision["level"] != 3, "Writing code about Chrome should NOT be Level 3"

    def test_essay_topic_with_chrome_is_not_os(self):
        decision = _engine().decide("the topic is Chrome browser security")
        assert decision["level"] != 3

    def test_word_count_mentioning_word_is_not_os(self):
        decision = _engine().decide("the word count should be between 250 and 280")
        assert decision["level"] != 3
        assert decision.get("application") != "word"

    def test_run_code_is_not_application_open(self):
        decision = _engine().decide("run this Python code")
        assert decision["level"] != 3
        assert decision.get("intent") != "application.open"

    def test_execute_function_is_not_application_open(self):
        decision = _engine().decide("execute this function")
        assert decision["level"] != 3

    def test_start_writing_is_not_application_open(self):
        decision = _engine().decide("start writing your essay")
        assert decision["level"] != 3

    def test_open_topic_is_not_application_open(self):
        decision = _engine().decide("open topic for discussion")
        assert decision["level"] != 3

    def test_check_grammar_is_not_application_inspect(self):
        decision = _engine().decide("check grammar of this sentence")
        assert decision["level"] != 3

    def test_ielts_essay_is_not_os(self):
        decision = _engine().decide(
            "write an IELTS essay on the topic "
            "develop countries uses more fuel. "
            "The word count should be between 250 and 280."
        )
        assert decision["level"] != 3

    def test_long_conversational_request_with_question_is_not_os(self):
        """A question about an application should not be OS execution."""
        decision = _engine().decide(
            "What is the difference between Chrome and Firefox?"
        )
        assert decision["level"] != 3

    def test_what_does_running_mean_is_not_inspect(self):
        """'running' in an educational context must not trigger application.inspect."""
        decision = _engine().decide(
            "What does the word 'running' mean in English?"
        )
        assert decision["level"] != 3

    def test_normal_question_stays_out_of_os(self):
        """Confirm the core regression from the existing test suite."""
        decision = _engine().decide("is this IELTS sentence correct?")
        assert decision["level"] != 3


# =========================================================
# 3. ENTITY UNDERSTANDING
#    Different entity references resolve to the same entity
# =========================================================


class TestEntityUnderstanding:
    """Different phrasings of the same entity should resolve identically."""

    def test_open_chrome_and_open_google_chrome_resolve_same_app(self):
        """'Open Chrome' and 'Open Google Chrome' should both resolve Chrome."""
        d1 = _engine().decide("Open Chrome")
        d2 = _engine().decide("Open Google Chrome")
        assert d1["level"] == 3
        assert d2["level"] == 3
        assert d1["application"] == d2["application"] == "chrome"

    def test_downloads_folder_standard_patterns(self):
        """Standard folder open patterns should all route to Level 3."""
        d1 = _engine().decide("open my Downloads folder")
        d2 = _engine().decide("open Downloads")
        assert d1["level"] == 3
        assert d2["level"] == 3

    def test_documents_folder_synonyms(self):
        """'documents' and 'open documents' should both route to Level 3."""
        d1 = _engine().decide("open documents")
        d2 = _engine().decide("open the documents folder")
        assert d1["level"] == 3
        assert d2["level"] == 3

    def test_word_application_always_resolves_to_word(self):
        """Microsoft Word should always resolve to 'word'."""
        variants = ["Open Word", "Launch Microsoft Word", "Start Word"]
        for text in variants:
            decision = _engine().decide(text)
            assert decision["application"] is not None
            assert "word" in decision["application"].lower()

    def test_excel_always_resolves_to_excel(self):
        """Microsoft Excel should always resolve to 'excel'."""
        variants = ["Open Excel", "Launch Microsoft Excel"]
        for text in variants:
            decision = _engine().decide(text)
            assert decision["application"] is not None
            assert "excel" in decision["application"].lower()

    def test_vscode_aliases_resolve_to_vscode(self):
        """Various VS Code aliases should all resolve to vscode."""
        variants = ["Open VS Code", "Launch Visual Studio Code", "Start vscode"]
        for text in variants:
            decision = _engine().decide(text)
            assert decision["application"] is not None
            assert "vscode" in decision["application"].lower()

    def test_folder_alias_consistency(self):
        """Standard folder names should resolve consistently."""
        folders = ["downloads", "documents", "desktop", "pictures", "music", "videos"]
        for folder in folders:
            d1 = _engine().decide(f"open {folder}")
            d2 = _engine().decide(f"open my {folder} folder")
            assert d1["level"] == 3, f"'open {folder}' should be Level 3"
            assert d2["level"] == 3, f"'open my {folder} folder' should be Level 3"

    def test_chrome_canonical_name_is_consistent(self):
        """Multiple Chrome references should all resolve to 'chrome'."""
        variants = [
            "Open Chrome",
            "Launch Google Chrome",
            "Start Chrome up",
        ]
        for text in variants:
            d = _engine().decide(text)
            assert d["application"] is not None
            assert d["application"].lower() == "chrome"


# =========================================================
# 4. CONSTRAINT UNDERSTANDING
#    Different constraint phrasings map to same semantics
# =========================================================


class TestConstraintUnderstanding:
    """Different phrasings of constraints should map to the same semantic meaning."""

    def test_newest_constraint_detected_via_objective_understanding(self):
        """'newest' should be detected as a recency constraint."""
        engine = FakeDecisionEngine({
            "find the newest spreadsheet": _decision(
                "find the newest spreadsheet",
                operation="file.search",
                target="spreadsheet",
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("find the newest spreadsheet")
        assert result.executable is True
        assert "latest_only" in result.steps[0].constraints

    def test_latest_constraint_detected(self):
        engine = FakeDecisionEngine({
            "find the latest spreadsheet": _decision(
                "find the latest spreadsheet",
                operation="file.search",
                target="spreadsheet",
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("find the latest spreadsheet")
        assert result.executable is True
        assert "latest_only" in result.steps[0].constraints

    def test_delete_constraint_detected(self):
        """'delete' operations should carry destructive constraints."""
        engine = FakeDecisionEngine({
            "delete the old report": _decision(
                "delete the old report",
                operation="file.delete",
                target="report",
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("delete the old report")
        assert result.executable is True
        assert "destructive_operation" in result.steps[0].constraints

    def test_move_constraint_detected(self):
        """'move' operations should carry modifies_existing constraint."""
        engine = FakeDecisionEngine({
            "move files to Reports": _decision(
                "move files to Reports",
                operation="file.move",
                target="Reports",
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("move files to Reports")
        assert result.executable is True
        assert "modifies_existing" in result.steps[0].constraints

    def test_dangerous_delete_has_high_risk(self):
        """File deletion should be classified as high risk."""
        engine = FakeDecisionEngine({
            "delete report.xlsx": _decision(
                "delete report.xlsx",
                operation="file.delete",
                target="report.xlsx",
                confidence=0.99,
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("delete report.xlsx")
        assert result.executable is True
        assert result.steps[0].risk == "high"

    def test_move_has_medium_risk(self):
        """File move should be classified as medium risk."""
        engine = FakeDecisionEngine({
            "move files to Reports": _decision(
                "move files to Reports",
                operation="file.move",
                target="Reports",
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("move files to Reports")
        assert result.executable is True
        assert result.steps[0].risk == "medium"

    def test_copy_constraint_detected(self):
        """'copy' operations should carry preserves_source constraint."""
        engine = FakeDecisionEngine({
            "copy files to backup": _decision(
                "copy files to backup",
                operation="file.copy",
                target="backup",
            ),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("copy files to backup")
        assert result.executable is True
        assert "preserves_source" in result.steps[0].constraints


# =========================================================
# 5. CAPABILITY REGISTRY COVERAGE
#    Verify new capabilities exist and are registered
# =========================================================


class TestCapabilityRegistryCoverage:
    """Verify that new capabilities from Level 3.10+ are registered."""

    def test_gui_focus_window_registered(self):
        assert CapabilityRegistry.exists("gui.focus_window"), \
            "gui.focus_window should be registered"

    def test_gui_type_text_registered(self):
        assert CapabilityRegistry.exists("gui.type_text"), \
            "gui.type_text should be registered"

    def test_gui_click_registered(self):
        assert CapabilityRegistry.exists("gui.click"), \
            "gui.click should be registered"

    def test_document_read_registered(self):
        assert CapabilityRegistry.exists("document.read"), \
            "document.read should be registered"

    def test_document_inspect_intel_registered(self):
        assert CapabilityRegistry.exists("document.inspect_intel"), \
            "document.inspect_intel should be registered"

    def test_document_search_intel_registered(self):
        assert CapabilityRegistry.exists("document.search_intel"), \
            "document.search_intel should be registered"

    def test_spreadsheet_read_intel_registered(self):
        assert CapabilityRegistry.exists("spreadsheet.read_intel"), \
            "spreadsheet.read_intel should be registered"

    def test_spreadsheet_inspect_intel_registered(self):
        assert CapabilityRegistry.exists("spreadsheet.inspect_intel"), \
            "spreadsheet.inspect_intel should be registered"

    def test_spreadsheet_calculate_registered(self):
        assert CapabilityRegistry.exists("spreadsheet.calculate"), \
            "spreadsheet.calculate should be registered"

    def test_spreadsheet_rank_registered(self):
        assert CapabilityRegistry.exists("spreadsheet.rank"), \
            "spreadsheet.rank should be registered"

    def test_spreadsheet_sort_registered(self):
        assert CapabilityRegistry.exists("spreadsheet.sort"), \
            "spreadsheet.sort should be registered"

    def test_gui_capabilities_are_enabled(self):
        for op in ("gui.focus_window", "gui.type_text", "gui.click"):
            cap = CapabilityRegistry.get(op)
            assert cap is not None, f"{op} should exist"
            assert cap.enabled is True, f"{op} should be enabled"

    def test_document_read_is_enabled(self):
        cap = CapabilityRegistry.get("document.read")
        assert cap is not None
        assert cap.enabled is True

    def test_spreadsheet_sort_is_enabled(self):
        cap = CapabilityRegistry.get("spreadsheet.sort")
        assert cap is not None
        assert cap.enabled is True

    def test_gui_capabilities_classified_as_supported(self):
        for op in ("gui.focus_window", "gui.type_text", "gui.click"):
            assert CapabilityRegistry.classify(op) == "supported", \
                f"{op} should be classified as 'supported'"

    def test_document_read_classified_as_supported(self):
        assert CapabilityRegistry.classify("document.read") == "supported"

    def test_spreadsheet_sort_classified_as_supported(self):
        assert CapabilityRegistry.classify("spreadsheet.sort") == "supported"

    def test_gui_capabilities_pass_execution_safety(self):
        for op in ("gui.focus_window", "gui.type_text", "gui.click"):
            result = ExecutionSafety.check(op)
            assert result.status == "supported", \
                f"{op} should be 'supported' in ExecutionSafety, got {result.status}"

    def test_document_read_passes_execution_safety(self):
        result = ExecutionSafety.check("document.read")
        assert result.status == "supported"

    def test_spreadsheet_sort_passes_execution_safety(self):
        result = ExecutionSafety.check("spreadsheet.sort")
        assert result.status == "supported"


# =========================================================
# 6. COMPOUND TASK DETECTION
#    Multi-step objectives decompose into multiple steps
# =========================================================


class TestCompoundTaskDetection:
    """Multi-step objectives should decompose into individual steps."""

    def test_open_folder_find_spreadsheet_calculate_rank(self):
        """Complex multi-step objective should decompose into multiple steps."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open my results folder": _decision(
                "open my results folder",
                operation="folder.open",
                target="results",
            ),
            "find the newest spreadsheet": _decision(
                "find the newest spreadsheet",
                operation="file.search",
                target="spreadsheet",
            ),
            "calculate percentages": _decision(
                "calculate percentages",
                operation="spreadsheet.calculate",
                target="percentages",
            ),
            "rank students": _decision(
                "rank students",
                operation="spreadsheet.rank",
                target="students",
            ),
        }))

        result = objectives.understand(
            "open my results folder, find the newest spreadsheet, "
            "calculate percentages, then rank students"
        )

        assert result.executable is True
        assert len(result.steps) >= 3, \
            f"Expected at least 3 steps, got {len(result.steps)}"

    def test_simple_task_stays_single_step(self):
        """A simple task should not be over-decomposed."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        }))

        result = objectives.understand("open Chrome")

        assert result.executable is True
        assert len(result.steps) == 1

    def test_compound_objective_preserves_step_order(self):
        """Decomposed steps should preserve user's intended order."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "search for music": _decision(
                "search for music",
                operation="browser.search",
                target="music",
            ),
            "open Word": _decision("open Word", target="Word"),
        }))

        result = objectives.understand(
            "open Chrome and search for music, then open Word"
        )

        assert result.executable is True
        assert [s.text for s in result.steps] == [
            "open Chrome",
            "search for music",
            "open Word",
        ]

    def test_compound_level3_steps_are_fully_level3(self):
        """All Level 3 steps should make the objective fully Level 3."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "open Word": _decision("open Word", target="Word"),
        }))

        result = objectives.understand("open Chrome and open Word")

        assert result.fully_level3 is True

    def test_non_level3_step_blocks_execution(self):
        """If the decision engine returns Level 1 for a fragment, it blocks execution."""
        # The FakeDecisionEngine has substring fallback, so "open Chrome and explain
        # this sentence" matches "open Chrome" and returns Level 3. To test the
        # blocking behavior, use a strict engine that has no matching key.
        class StrictFakeDecisionEngine:
            def __init__(self, decisions):
                self.decisions = decisions
                self.calls = []
            def decide(self, text):
                self.calls.append(text)
                return self.decisions.get(text, {
                    "level": 1,
                    "mode": "conversation",
                    "task": text,
                    "confidence": 0.5,
                })

        engine = StrictFakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        })
        objectives = ObjectiveUnderstanding(engine)
        result = objectives.understand(
            "open Chrome and explain this sentence"
        )
        # The full fragment goes to the engine, which returns Level 1
        assert result.executable is False
        assert result.fully_level3 is False

    def test_comma_separated_steps_preserve_order(self):
        """Comma-separated actions should be decomposed in order."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "open Word": _decision("open Word", target="Word"),
        }))

        result = objectives.understand("open Chrome, open Word")

        assert len(result.steps) == 2
        assert result.steps[0].text == "open Chrome"
        assert result.steps[1].text == "open Word"

    def test_compound_with_multiple_action_verbs(self):
        """Steps joined by 'and' + action verb should decompose."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "search for music": _decision(
                "search for music",
                operation="browser.search",
                target="music",
            ),
        }))

        result = objectives.understand("open Chrome and search for music")
        assert len(result.steps) == 2


# =========================================================
# 7. MIXED LEVEL ROUTING
#    Level 2 + Level 3 in one request
# =========================================================


class TestMixedLevelRouting:
    """Requests that combine OS actions and agent tasks should detect both levels."""

    def test_analyze_excel_and_save_cleaned_version(self):
        """'Analyze this Excel file and save a cleaned version' → Level 2 + Level 3."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "analyze this excel file": {
                "level": 2,
                "mode": "single_agent",
                "agent": "Data Agent",
                "agents": ["Data Agent"],
                "task": "analyze this excel file",
                "confidence": 0.88,
            },
            "save a cleaned version": _decision(
                "save a cleaned version",
                operation="file.save",
                target="cleaned version",
            ),
        }))

        result = objectives.understand(
            "analyze this excel file and save a cleaned version"
        )

        assert len(result.steps) == 2
        assert result.steps[0].level == 2
        assert result.steps[1].level == 3
        assert result.fully_level3 is False

    def test_pure_level3_compound_is_fully_executable(self):
        """Pure Level 3 compound tasks should be fully executable."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "open Word": _decision("open Word", target="Word"),
        }))

        result = objectives.understand("open Chrome and open Word")
        assert result.fully_level3 is True
        assert result.executable is True

    def test_mixed_level_not_fully_executable(self):
        """When the FakeDecisionEngine returns a mix, it should not be fully executable.

        Level 3.19 added context-aware re-resolution for the
        2nd clause. The 2nd clause "write me a poem" is a
        Level 1 conversation request that the context
        resolver does not (and should not) map to an OS
        action, so the compound result is mixed-level.
        """
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        })
        objectives = ObjectiveUnderstanding(engine)
        result = objectives.understand("open Chrome and write me a poem")
        assert result.fully_level3 is False

    def test_two_level3_steps_with_search_and_open(self):
        """Two Level 3 steps joined by 'and' should both be executable."""
        objectives = ObjectiveUnderstanding(FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "search for music": _decision(
                "search for music",
                operation="browser.search",
                target="music",
            ),
        }))

        result = objectives.understand("open Chrome and search for music")
        assert len(result.steps) == 2
        assert result.steps[0].level == 3
        assert result.steps[1].level == 3
        assert result.fully_level3 is True
        assert result.executable is True


# =========================================================
# 8. RECOVERY STRATEGY TESTS
#    Recovery strategies exist and apply correctly
# =========================================================


class TestRecoveryStrategyTests:
    """Recovery engine should have strategies for common failure modes."""

    def _make_engine(self):
        from genesis_os.recovery_engine import RecoveryEngine
        from genesis_os.os_manager import OSManager
        os_manager = Mock(spec=OSManager)
        return RecoveryEngine(os_manager)

    def test_application_launch_fallback_strategy_exists(self):
        strategy = self._make_engine().get_strategy("application_launch_fallback")
        assert strategy is not None
        assert strategy.max_attempts >= 2

    def test_file_path_fallback_strategy_exists(self):
        strategy = self._make_engine().get_strategy("file_path_fallback")
        assert strategy is not None
        assert strategy.max_attempts >= 2

    def test_folder_path_fallback_strategy_exists(self):
        strategy = self._make_engine().get_strategy("folder_path_fallback")
        assert strategy is not None

    def test_window_focus_fallback_strategy_exists(self):
        strategy = self._make_engine().get_strategy("window_focus_fallback")
        assert strategy is not None

    def test_alternative_application_strategy_exists(self):
        strategy = self._make_engine().get_strategy("alternative_application")
        assert strategy is not None

    def test_state_reobservation_strategy_exists(self):
        strategy = self._make_engine().get_strategy("state_reobservation")
        assert strategy is not None

    def test_application_launch_recovery_finds_applicable_strategy(self):
        strategies = self._make_engine().find_applicable_strategies(
            "application.open", "launch_failed"
        )
        assert len(strategies) >= 1
        assert any(s.name == "application_launch_fallback" for s in strategies)

    def test_file_path_recovery_finds_applicable_strategy(self):
        strategies = self._make_engine().find_applicable_strategies(
            "file.open", "file_not_found"
        )
        assert len(strategies) >= 1
        assert any(s.name == "file_path_fallback" for s in strategies)

    def test_all_strategies_have_bounded_attempts(self):
        engine = self._make_engine()
        for strategy in engine.list_strategies():
            assert strategy.max_attempts > 0, \
                f"Strategy '{strategy.name}' must have bounded attempts"
            assert strategy.max_attempts <= 5, \
                f"Strategy '{strategy.name}' should not exceed 5 attempts"

    def test_strategies_have_descriptions(self):
        engine = self._make_engine()
        for strategy in engine.list_strategies():
            assert strategy.description, \
                f"Strategy '{strategy.name}' must have a description"

    def test_strategy_version_is_set(self):
        engine = self._make_engine()
        assert engine.VERSION is not None


# =========================================================
# 9. SESSION STATE TESTS
#    Multi-turn continuation uses context correctly
# =========================================================


class TestSessionStateTests:
    """Session context should bind follow-up requests to previous turns."""

    def test_session_binder_requires_decision_engine(self):
        from genesis_os.session_context import SessionContextBinder
        with pytest.raises(TypeError):
            SessionContextBinder(None)

    def test_session_binder_has_try_rebind(self):
        """SessionContextBinder should have try_rebind method."""
        from genesis_os.session_context import SessionContextBinder
        engine = _engine()
        binder = SessionContextBinder(engine)
        assert hasattr(binder, "try_rebind")

    def test_session_binder_has_record_decision(self):
        """SessionContextBinder should have record_decision method."""
        from genesis_os.session_context import SessionContextBinder
        engine = _engine()
        binder = SessionContextBinder(engine)
        assert hasattr(binder, "record_decision")

    def test_session_binder_rejects_unbound_anaphora(self):
        """Requests referencing live UI state should be declined."""
        from genesis_os.session_context import SessionContextBinder

        engine = _engine()
        binder = SessionContextBinder(engine)

        # Set up context first
        binder.record_decision(
            _decision("open Chrome", target="Chrome")
        )

        # Anaphoric request that references live state
        result = binder.try_rebind("open the first result")
        # Should be None since we can't observe live browser state
        assert result is None

    def test_session_context_stores_last_intent(self):
        """After recording a decision, the session context should remember intent."""
        from genesis_os.session_context import SessionContextBinder

        engine = _engine()
        binder = SessionContextBinder(engine)

        decision = _decision(
            "open my results folder",
            operation="folder.open",
            target="results",
        )
        binder.record_decision(decision)

        assert binder._intent == "folder.open"
        assert binder._target == "results"

    def test_session_context_resets_on_new_decision(self):
        """A new recording should replace the previous context."""
        from genesis_os.session_context import SessionContextBinder

        engine = _engine()
        binder = SessionContextBinder(engine)

        binder.record_decision(_decision("open Chrome", target="Chrome"))
        assert binder._application is not None

        first_app = binder._application
        binder.record_decision(_decision("open Word", target="Word"))
        assert binder._application is not None
        assert binder._application != first_app

    def test_session_context_has_context_after_record(self):
        """has_context should be True after recording a decision."""
        from genesis_os.session_context import SessionContextBinder

        engine = _engine()
        binder = SessionContextBinder(engine)

        assert binder.has_context is False
        binder.record_decision(_decision("open Chrome", target="Chrome"))
        assert binder.has_context is True

    def test_session_context_reset_clears_state(self):
        """reset() should clear all stored context."""
        from genesis_os.session_context import SessionContextBinder

        engine = _engine()
        binder = SessionContextBinder(engine)

        binder.record_decision(_decision("open Chrome", target="Chrome"))
        assert binder.has_context is True

        binder.reset()
        assert binder.has_context is False

    def test_try_rebind_returns_none_without_context(self):
        """try_rebind should return None when there's no context."""
        from genesis_os.session_context import SessionContextBinder

        engine = _engine()
        binder = SessionContextBinder(engine)

        result = binder.try_rebind("open the newest spreadsheet")
        assert result is None


# =========================================================
# 10. OBSERVATION LOOP COVERAGE
#     Verify enhanced observation works for all categories
# =========================================================


class TestObservationLoopCoverage:
    """Enhanced observation should cover all Level 3 operation categories."""

    def test_enhanced_observation_module_exists(self):
        from genesis_os.enhanced_observation import EnhancedObservationLoop
        assert EnhancedObservationLoop is not None

    def test_enhanced_observation_result_structure(self):
        from genesis_os.enhanced_observation import EnhancedObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"running": True},
            actual_state={"running": True},
            matches_expected=True,
        )
        assert result.step_id == "step-1"
        assert result.operation == "application.open"
        assert result.matches_expected is True

    def test_enhanced_observation_result_to_dict(self):
        from genesis_os.enhanced_observation import EnhancedObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"running": True},
            actual_state={"running": True},
            matches_expected=True,
        )
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["step_id"] == "step-1"
        assert data["matches_expected"] is True

    def test_enhanced_observation_result_to_observation_result(self):
        from genesis_os.enhanced_observation import EnhancedObservationResult
        from genesis_os.observation_loop import ObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"running": True},
            actual_state={"running": True},
            matches_expected=True,
        )
        base = result.to_observation_result()
        assert isinstance(base, ObservationResult)
        assert base.step_id == "step-1"

    def test_observation_loop_module_exists(self):
        from genesis_os.observation_loop import ObservationLoop
        assert ObservationLoop is not None

    def test_enhanced_observation_result_has_enhanced_checks(self):
        """EnhancedObservationResult should support enhanced_checks dict."""
        from genesis_os.enhanced_observation import EnhancedObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"running": True},
            actual_state={"running": True},
            matches_expected=True,
            enhanced_checks={"process_running": True},
        )
        assert result.enhanced_checks["process_running"] is True

    def test_enhanced_observation_handles_discrepancy(self):
        """When expected and actual state differ, discrepancy should be reported."""
        from genesis_os.enhanced_observation import EnhancedObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"running": True},
            actual_state={"running": False},
            matches_expected=False,
            discrepancy="Application not found running",
        )
        assert result.matches_expected is False
        assert result.discrepancy == "Application not found running"

    def test_observation_result_confidence_scoring(self):
        """Enhanced observation should have confidence scoring."""
        from genesis_os.enhanced_observation import EnhancedObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={"running": True},
            actual_state={"running": True},
            matches_expected=True,
            confidence=0.95,
        )
        assert result.confidence == 0.95

    def test_enhanced_observation_result_default_confidence(self):
        """Default confidence should be 1.0."""
        from genesis_os.enhanced_observation import EnhancedObservationResult

        result = EnhancedObservationResult(
            step_id="step-1",
            operation="application.open",
            target="Chrome",
            expected_state={},
            actual_state={},
            matches_expected=True,
        )
        assert result.confidence == 1.0


# =========================================================
# INTEGRATION: Full Pipeline Tests
# =========================================================


class TestGeneralizationIntegration:
    """End-to-end tests verifying the full pipeline works together."""

    def test_understanding_to_decomposition_pipeline(self):
        """ObjectiveUnderstanding → WorkflowDecomposer should produce executable workflow."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
            "search for music": _decision(
                "search for music",
                operation="browser.search",
                target="music",
            ),
        })

        understanding = ObjectiveUnderstanding(engine).understand(
            "open Chrome and search for music"
        )
        result = WorkflowDecomposer().decompose(understanding)

        assert result.executable is True
        assert result.workflow is not None
        assert len(result.workflow.steps) == 2

    def test_clarification_blocks_decomposition(self):
        """When understanding requires clarification, decomposition should not execute."""
        engine = FakeDecisionEngine({
            "open something": _decision(
                "open something",
                target=None,
                confidence=0.5,
            ),
        })

        understanding = ObjectiveUnderstanding(engine).understand(
            "open something"
        )

        assert understanding.requires_clarification is True
        assert understanding.executable is False

    def test_routing_engine_deterministic(self):
        """The same input should always produce the same decision."""
        engine = _engine()
        d1 = engine.decide("open Chrome")
        d2 = engine.decide("open Chrome")
        assert d1["level"] == d2["level"]
        assert d1["intent"] == d2["intent"]
        assert d1["application"] == d2["application"]

    def test_routing_engine_explain_provides_metadata(self):
        """The explain() method should provide routing metadata."""
        engine = _engine()
        result = engine.explain("open Chrome")
        assert "input" in result
        assert "decision" in result
        assert "engine" in result
        assert result["decision"]["level"] == 3

    def test_objective_understanding_version_is_set(self):
        understanding = ObjectiveUnderstanding(FakeDecisionEngine({}))
        assert understanding.VERSION is not None

    def test_empty_objective_returns_clarification(self):
        understanding = ObjectiveUnderstanding(FakeDecisionEngine({}))
        result = understanding.understand("")
        assert result.requires_clarification is True
        assert result.executable is False

    def test_capability_registry_version_deterministic(self):
        first = CapabilityRegistry.operations()
        second = CapabilityRegistry.operations()
        assert first == second

    def test_objective_understanding_result_has_to_dict(self):
        """ObjectiveUnderstandingResult should be serializable."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        })
        understanding = ObjectiveUnderstanding(engine)
        result = understanding.understand("open Chrome")
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["objective"] == "open Chrome"
        assert data["fully_level3"] is True
        assert data["executable"] is True

    def test_step_intent_has_to_dict(self):
        """ObjectiveStepIntent should be serializable."""
        intent = _make_intent()
        data = intent.to_dict()
        assert isinstance(data, dict)
        assert data["operation"] == "application.open"
        assert data["level"] == 3

    def test_decomposition_result_preserves_workflow_metadata(self):
        """Decomposition should preserve objective text in workflow."""
        engine = FakeDecisionEngine({
            "open Chrome": _decision("open Chrome", target="Chrome"),
        })
        understanding = ObjectiveUnderstanding(engine).understand("open Chrome")
        result = WorkflowDecomposer().decompose(
            understanding, workflow_id="test-001"
        )
        assert result.workflow is not None
        assert result.workflow.workflow_id == "test-001"
        assert result.workflow.objective == "open Chrome"
