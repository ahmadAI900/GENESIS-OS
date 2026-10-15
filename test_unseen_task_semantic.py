"""
Genesis OS — Unseen Task Semantic Classifier Regression Tests.

These tests exercise the deterministic semantic classifier that
fixes a real failure cluster measured on UNSEEN natural-language
tasks. Every test probes multiple PARAPHRASES of the same
underlying intent so the classifier is held to architectural
generalisation, not memorised sentences.

The classifier lives in ``agents.unseen_task_semantic`` and is
wired into ``WorkflowDecisionEngine._detect_os_intent``.

Spec compliance
---------------
* Each test family asserts both POSITIVE cases (the unseen
  phrasings should now route to Level 3 OS) and NEGATIVE cases
  (the false-positive protections: "start writing", "open the
  discussion", "open my downloads" still route correctly).
* One family is an exception and says so on the class:
  ``file.rename`` declares ``new_name`` as a required input, so an
  anaphoric rename with no new name is correctly refused rather than
  promoted. See ``TestAnaphoricFileRenameParaphrases``.
* Tests are independent of the AI engine / network / LLM and
  therefore stable in CI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from agents.unseen_task_semantic import (
    UnseenTaskSemanticClassifier,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def engine():
    return WorkflowDecisionEngine()


@pytest.fixture
def classifier():
    return UnseenTaskSemanticClassifier()


# ---------------------------------------------------------------------
# POSITIVE PARAPHRASE TESTS
#
# Each parametrize block probes multiple unseen phrasings of the
# SAME underlying intent. The classifier must recognise the
# family, not memorise the sentence.
# ---------------------------------------------------------------------


class TestAnaphoricFileMoveParaphrases:
    """Anaphoric file move: 'the file I just edited' + destination."""

    @pytest.mark.parametrize(
        "text,expected_destination",
        [
            ("put the file I just edited into the Reports folder", "reports"),
            ("move the document I was working on into the backups folder", "backups"),
            ("the pdf I just saved, put it in the reports", "reports"),
            ("move my active spreadsheet to the workspace", "workspace"),
            ("move the open document to the desktop", "desktop"),
            ("put the file I was editing into my Reports folder", "reports"),
        ],
    )
    def test_routes_to_l3_file_move(
        self, engine, text, expected_destination
    ):
        decision = engine.decide(text)
        assert decision["level"] == 3, (
            f"Expected L3 for {text!r}, got {decision['level']} "
            f"({decision.get('mode')!r})"
        )
        assert decision["mode"] == "os"
        assert decision.get("intent") == "file.move"
        params = decision.get("parameters", {})
        assert params.get("source_is_anaphoric") is True
        assert params.get("requires_confirmation") is True
        assert (
            decision.get("target") == expected_destination
            or expected_destination in (decision.get("target") or "")
        )


class TestAnaphoricFileCopyParaphrases:
    """Anaphoric file copy: 'save a copy of the open pdf' etc."""

    @pytest.mark.parametrize(
        "text",
        [
            "save a copy of the open document onto my desktop",
            "save a copy of the open pdf onto my desktop",
            "duplicate the file I was editing into the backups",
            "make a backup of the report I was viewing",
        ],
    )
    def test_routes_to_l3_file_copy(self, engine, text):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["mode"] == "os"
        assert decision.get("intent") == "file.copy"
        params = decision.get("parameters", {})
        assert params.get("source_is_anaphoric") is True


class TestAnaphoricFileDeleteParaphrases:
    """Anaphoric file delete requires confirmation."""

    @pytest.mark.parametrize(
        "text",
        [
            "delete the file we were looking at",
            "remove the document I just opened",
            "trash the spreadsheet I was editing yesterday",
        ],
    )
    def test_routes_to_l3_file_delete(self, engine, text):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["mode"] == "os"
        assert decision.get("intent") == "file.delete"
        params = decision.get("parameters", {})
        assert params.get("requires_confirmation") is True


class TestAnaphoricFileRenameParaphrases:
    """Anaphoric file rename with no new name must NOT reach Level 3.

    ``file.rename`` declares ``new_name`` as a required input. An
    anaphoric rename supplies the SOURCE ("the file I just created")
    and nothing else, so the required input is absent and the
    control plane refuses the capability. Failing to resolve is the
    correct outcome: a rename with no destination name is not an
    executable request, and silently inventing a name would be worse
    than declining.

    What the system SHOULD do instead -- ask the user for the missing
    name rather than dropping to Level 1 -- is a Human Escalation
    concern tracked in the Phase 3 closeout, not something this test
    asserts as working. These tests therefore pin three separate
    facts, because the old single assertion conflated them:
    recognition is intact, resolution is correctly refused, and the
    refusal is caused by precisely the missing input.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "rename the file I just created",
            "rename the document I was editing",
        ],
    )
    def test_recognition_is_intact(self, classifier, text):
        """The semantic classifier still fires on the rename family."""
        detected = classifier.classify(text)
        assert detected is not None, (
            f"rename family not recognised for {text!r}"
        )
        assert detected.family == "anaphoric_file_rename"
        assert detected.intent == "file.rename"
        params = detected.parameters
        assert params.get("source_is_anaphoric") is True
        assert params.get("requires_confirmation") is True

    @pytest.mark.parametrize(
        "text",
        [
            "rename the file I just created",
            "rename the document I was editing",
        ],
    )
    def test_does_not_reach_level_3(self, engine, text):
        """No new name supplied => no Level 3 OS decision."""
        decision = engine.decide(text)
        assert decision["level"] != 3, (
            f"Unmet precondition must not produce L3 for {text!r}, "
            f"got L{decision['level']} intent={decision.get('intent')!r}"
        )
        assert decision["mode"] != "os"
        assert not decision.get("intent")

    def test_refusal_is_caused_by_the_missing_input(self, engine):
        """The drop is the precondition, not something else about the
        request: supplying ``new_name`` resolves the same capability."""
        from genesis_os.capability_registry import CapabilityRegistry
        from genesis_os.capability_resolver import (
            CapabilityResolutionStatus,
        )

        assert CapabilityRegistry.get("file.rename").preconditions == (
            "new_name",
        )

        without = engine.capability_resolver.resolve_operation(
            "file.rename",
            description="rename the file I just created",
            inputs={"source_is_anaphoric", "requires_target"},
        )
        assert without.status is (
            CapabilityResolutionStatus.UNAVAILABLE
        )
        assert "new_name" in without.explanation

        with_input = engine.capability_resolver.resolve_operation(
            "file.rename",
            description="rename the file I just created",
            inputs={"new_name", "requires_target"},
        )
        assert with_input.status is CapabilityResolutionStatus.RESOLVED


class TestAnaphoricFileOpenParaphrases:
    """Anaphoric file open: 'open the spreadsheet I was editing'."""

    @pytest.mark.parametrize(
        "text",
        [
            "open the spreadsheet I was editing yesterday",
            "open the document I just modified",
            "open the file I was viewing",
        ],
    )
    def test_routes_to_l3_file_open(self, engine, text):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["mode"] == "os"
        # The engine may route to the generic file.open
        # OR to a file-family specific intent
        # (spreadsheet.inspect / document.read) when the
        # noun is a specific file family. Both are
        # architecturally correct; the file-family intent
        # is more specific.
        intent = decision.get("intent") or ""
        assert (
            intent == "file.open"
            or intent.startswith("spreadsheet.")
            or intent.startswith("document.")
        ), f"Unexpected intent: {intent}"
        # Either the semantic classifier or the natural-file-open
        # regex may have produced this decision; both are valid.
        # What matters is that the OS intent was recognised.
        params = decision.get("parameters", {})
        # Anaphoric source is acceptable but not required:
        # the natural-file regex path also produces file.open.
        assert isinstance(params, dict)


class TestMathNaturalLanguageParaphrases:
    """Math NL without 'calculate' keyword."""

    @pytest.mark.parametrize(
        "text,expected_expr_contains",
        [
            ("what is 17% of 2450 and add it to 800", "2450"),
            ("17% of 2450", "2450"),
            ("17 percent of 2450 plus 800", "2450"),
            ("2450 plus 800", "2450"),
            ("what is 9 * 9", "9"),
            ("100 divided by 4", "100"),
            ("25 times 4", "25"),
        ],
    )
    def test_routes_to_l3_math_evaluate(
        self, engine, text, expected_expr_contains
    ):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["mode"] == "os"
        assert decision.get("intent") == "math.evaluate"
        params = decision.get("parameters", {})
        expr = params.get("expression") or decision.get("target")
        assert expr is not None
        assert expected_expr_contains in expr


class TestWindowDesktopIdiomsParaphrases:
    """Window / desktop control idioms."""

    @pytest.mark.parametrize(
        "text,expected_intent",
        [
            ("shut everything down and give me a clean desktop", "window.minimize_all"),
            ("show me the desktop", "window.show_desktop"),
            ("clean up the desktop", "window.show_desktop"),
            ("hide everything", "window.minimize_all"),
            ("bring the windows back", "window.restore"),
            ("i want to see my desktop", "window.show_desktop"),
        ],
    )
    def test_routes_to_l3_window_op(
        self, engine, text, expected_intent
    ):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["mode"] == "os"
        assert decision.get("intent") == expected_intent


class TestArchiveZipParaphrases:
    """Archive / zip-up requests."""

    @pytest.mark.parametrize(
        "text",
        [
            "I need everything related to Project Alpha zipped up",
            "zip up everything related to Project Alpha",
            "compress the downloads folder",
            "archive my documents",
            "pack the photos into an archive",
        ],
    )
    def test_routes_to_l3_folder_organize(self, engine, text):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["mode"] == "os"
        assert decision.get("intent") == "folder.organize"
        params = decision.get("parameters", {})
        assert params.get("operation") == "archive"
        assert params.get("requires_confirmation") is True


# ---------------------------------------------------------------------
# FALSE-POSITIVE PROTECTION TESTS
#
# These guard against the classifier stealing legitimate Level 1,
# Level 2 or other Level 3 routes.
# ---------------------------------------------------------------------


class TestStandardUserFolderNotStolen:
    """Standard user folder opens must still route to folder.open,
    NOT to anaphoric file ops."""

    @pytest.mark.parametrize(
        "text",
        [
            "open my downloads folder",
            "open my documents",
            "open my desktop folder",
            "open my downloads",
            "show me the downloads folder",
            "go to my downloads",
            "open my documents folder",
        ],
    )
    def test_routes_to_folder_open_not_anaphoric_file(
        self, engine, classifier, text
    ):
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision.get("intent") == "folder.open", (
            f"Expected folder.open for {text!r}, got "
            f"{decision.get('intent')!r}"
        )
        # Classifier must NOT have classified it as a file op.
        semantic = classifier.classify(text)
        assert semantic is None, (
            f"Classifier should not fire on {text!r} "
            f"(got family={semantic.family})"
        )


class TestAuthoringNotStolenAsApplicationOpen:
    """Authoring verbs like 'start writing' must NOT route to OS."""

    @pytest.mark.parametrize(
        "text",
        [
            "start writing my essay",
            "start writing your essay",
            "start coding the new feature",
        ],
    )
    def test_routes_to_conversation_or_agent_not_os(self, engine, text):
        decision = engine.decide(text)
        assert decision["level"] != 3, (
            f"Expected non-OS for {text!r}, got L{decision['level']} "
            f"intent={decision.get('intent')!r}"
        )


# ---------------------------------------------------------------------
# LEVEL 1 / LEVEL 2 COMPATIBILITY
# ---------------------------------------------------------------------


class TestLevel1And2RoutingUnchanged:
    """The classifier must not affect L1 conversation or L2 agent
    routing for tasks that have always been conversational."""

    @pytest.mark.parametrize(
        "text",
        [
            "hello, how are you?",
            "what is the meaning of life?",
            "tell me a joke",
            "remind me what we talked about yesterday about my python project",
        ],
    )
    def test_conversational_requests_unchanged(self, engine, text):
        decision = engine.decide(text)
        # Should NOT be a forced L3 OS for these.
        assert decision["level"] in (1, 2), (
            f"Expected L1/L2 for {text!r}, got L{decision['level']}"
        )


# ---------------------------------------------------------------------
# CLASSIFIER UNIT TESTS
# ---------------------------------------------------------------------


class TestClassifierUnit:
    """Direct unit tests of the UnseenTaskSemanticClassifier."""

    def test_returns_none_for_empty(self, classifier):
        assert classifier.classify("") is None
        assert classifier.classify("   ") is None

    def test_records_family_on_hit(self, classifier):
        d = classifier.classify(
            "put the file I just edited into the Reports folder"
        )
        assert d is not None
        assert d.family == "anaphoric_file_move"

    def test_math_expression_is_deterministic(self, classifier):
        d = classifier.classify("what is 17% of 2450")
        assert d is not None
        # The expression must be syntactically valid Python arithmetic.
        assert d.parameters["expression"] == "(17.0/100)*2450.0"

    def test_window_minimize_all_target(self, classifier):
        d = classifier.classify("shut everything down")
        assert d is not None
        assert d.intent == "window.minimize_all"
        assert d.target == "windows"

    def test_archive_marks_confirmation(self, classifier):
        d = classifier.classify("zip up my files")
        assert d is not None
        assert d.parameters["requires_confirmation"] is True
        assert d.parameters["requires_target"] is True

    def test_does_not_fire_on_obvious_conversation(self, classifier):
        assert classifier.classify("what is the capital of france") is None
        assert classifier.classify("tell me about photosynthesis") is None
        assert classifier.classify("hi there") is None


# ---------------------------------------------------------------------
# INTEGRATION: end-to-end pipeline still works through ActionExecutor
# ---------------------------------------------------------------------


class TestEndToEndPipelineStillExecutes:
    """The semantic decision must flow through the existing
    ActionExecutor without modification. We only assert the
    shape of the plan, not side-effects on a real OS.

    LIVE: the only test in this file that builds a real
    ``GenesisOS``, whose browser probe reaches the network and
    whose AI engine arms real cloud providers. Marked rather than
    moved, so the 59 offline assertions in this file stay in the
    fast default run.
    """

    @pytest.mark.live
    def test_anaphoric_move_plan_is_valid(
        self, engine, monkeypatch
    ):
        # Block any real side-effect by patching the executor.
        from genesis_os.action_plan import ActionPlan
        from genesis_os.action_result import ActionResult

        captured = {}

        def fake_execute(plan):
            captured["plan"] = plan
            return ActionResult(
                success=False,
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                status="blocked_by_test",
                message="captured",
                executed=False,
                verified=False,
                plan=plan,
            )

        from genesis import GenesisOS
        g = GenesisOS()
        # Patch the INSTANCE method (not the class) so the
        # bound self is preserved.
        monkeypatch.setattr(g.action_executor, "execute", fake_execute)

        decision = engine.decide(
            "put the file I just edited into the Reports folder"
        )
        assert decision["level"] == 3
        # Build a real ActionPlan and run it through the executor.
        plan = ActionPlan.from_decision(decision)
        g.action_executor.execute(plan)
        assert captured["plan"].operation == "file.move"
        assert captured["plan"].parameters.get("source_is_anaphoric") is True
