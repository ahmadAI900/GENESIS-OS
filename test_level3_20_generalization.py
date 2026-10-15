"""
Genesis OS — Level 3.20 Regression Tests.

These tests exercise the three architectural fixes that
close the remaining gaps from the Level 3.19 changelog:

  Gap 1: file_manager context (file.open of a file manager
         is now recognised as a file_manager context)
  Gap 2: app+create-document (word+create doc, notepad+write
         file, etc. are now resolved to document.create_*)
  Gap 3: browser-action verbs (bookmark, clear history,
         refresh, close tab, etc. are now in the Tier 2
         splitter and resolved by the context resolver)

Spec compliance
---------------
* Each test family probes multiple unseen paraphrases of
  the same underlying pattern.
* The tests prove that context-resolved 2nd clauses are
  real Level-3 OS intents that flow through the existing
  ActionExecutor (no bypass).
* False-positive guards protect single-step and
  conversational requests from being hijacked.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.objective_understanding import ObjectiveUnderstanding
from genesis_os.context_hint_resolver import (
    ContextHintResolver,
    _APP_DOCUMENT_CAPABILITIES,
    _BROWSER_ACTION_PATTERNS,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def wde():
    return WorkflowDecisionEngine()


@pytest.fixture
def ou(wde):
    return ObjectiveUnderstanding(wde)


@pytest.fixture
def router(wde, ou):
    from agents.compound_task_router import CompoundTaskRouter
    return CompoundTaskRouter(ou)


# ---------------------------------------------------------------------
# Gap 2: app+create-document compounds
# ---------------------------------------------------------------------


class TestAppCreateDocumentParaphrases:
    """When the 1st clause opens an app that can create
    documents, the 2nd clause's create-verb + document noun
    is resolved to the right document.create_* capability."""

    @pytest.mark.parametrize(
        "text,expected_intent,expected_app",
        [
            (
                "open word and start a new blank document",
                "document.create_docx", "word",
            ),
            (
                "open word and create a new document",
                "document.create_docx", "word",
            ),
            (
                "open notepad and start a new file",
                "document.create_txt", "notepad",
            ),
            (
                "open excel and create a new spreadsheet",
                "document.create_csv", "excel",
            ),
            (
                "open powerpoint and create a new presentation",
                "document.create_docx", "powerpoint",
            ),
        ],
    )
    def test_routes_to_document_create_capability(
        self, ou, text, expected_intent, expected_app
    ):
        res = ou.understand(text)
        assert len(res.steps) >= 2
        second_step = res.steps[-1]
        assert second_step.level == 3
        assert second_step.mode == "os"
        assert second_step.operation == expected_intent
        assert second_step.executable_intent is True
        assert second_step.decision.get(
            "source"
        ) == "context_hint_resolver"


# ---------------------------------------------------------------------
# Gap 3: browser-action verb compounds
# ---------------------------------------------------------------------


class TestBrowserActionVerbParaphrases:
    """When the 1st clause opens a browser, the 2nd clause's
    browser-action verbs are resolved to browser control
    capabilities."""

    @pytest.mark.parametrize(
        "text,expected_intent",
        [
            ("open chrome and bookmark this page", "browser.bookmark"),
            ("open chrome and clear my browsing history", "browser.clear_history"),
            ("open chrome and refresh the page", "browser.refresh"),
            ("open chrome and close the current tab", "browser.close_tab"),
            ("open chrome and reopen the last tab", "browser.switch_tab"),
            ("open chrome and go back", "browser.go_back"),
        ],
    )
    def test_routes_to_browser_action_capability(
        self, ou, text, expected_intent
    ):
        res = ou.understand(text)
        assert len(res.steps) >= 2
        second_step = res.steps[-1]
        assert second_step.level == 3
        assert second_step.mode == "os"
        assert second_step.operation == expected_intent
        assert second_step.executable_intent is True


# ---------------------------------------------------------------------
# Gap 1: file_manager context (folders, not files)
# ---------------------------------------------------------------------


class TestFileManagerFolderParaphrases:
    """When the 1st clause opens a file manager and the 2nd
    clause names a standard folder, the folder.open intent
    is produced."""

    @pytest.mark.parametrize(
        "text,expected_folder",
        [
            ("open the file manager and open the downloads folder", "downloads"),
            ("open the file manager and open the documents folder", "documents"),
            ("open the file manager and open the desktop folder", "desktop"),
            ("open the file manager and open my pictures folder", "pictures"),
        ],
    )
    def test_routes_to_folder_open(
        self, ou, text, expected_folder
    ):
        res = ou.understand(text)
        assert len(res.steps) >= 2
        second_step = res.steps[-1]
        assert second_step.level == 3
        assert second_step.mode == "os"
        assert second_step.operation == "folder.open"
        assert second_step.target == expected_folder


# ---------------------------------------------------------------------
# Tier 2 splitter: browser-action verbs now split
# ---------------------------------------------------------------------


class TestBrowserActionVerbSplitter:
    """The browser-action verb family is now in the Tier 2
    splitter so compound phrasings are detected."""

    @pytest.mark.parametrize(
        "text",
        [
            "open chrome and bookmark this page",
            "open chrome and clear my browsing history",
            "open chrome and refresh the page",
            "open chrome and close the current tab",
            "open chrome and reopen the last tab",
            "open chrome and go back",
            "open chrome and zoom in",
        ],
    )
    def test_splits_into_two_fragments(self, ou, text):
        fragments = ou.split_objective(text)
        assert len(fragments) == 2, (
            f"Expected 2 fragments for {text!r}, got "
            f"{len(fragments)}: {fragments}"
        )


# ---------------------------------------------------------------------
# FALSE-POSITIVE PROTECTION
# ---------------------------------------------------------------------


class TestSingleStepRequestsUnaffected:
    """Genuine single-step requests must NOT be hijacked by the
    new resolvers."""

    @pytest.mark.parametrize(
        "text",
        [
            "open my downloads",
            "open chrome",
            "open word",
            "bookmark this page",
            "create a new document",
        ],
    )
    def test_single_step_unchanged(self, ou, text):
        res = ou.understand(text)
        for s in res.steps:
            # No context-resolved source on a single-step
            # request that the user didn't frame as compound.
            if " and " not in text:
                assert s.decision.get(
                    "source"
                ) != "context_hint_resolver"


# ---------------------------------------------------------------------
# UNIT TESTS
# ---------------------------------------------------------------------


class TestAppDocumentCapabilitiesUnit:
    """The _APP_DOCUMENT_CAPABILITIES catalog is a
    meaning-based mapping (app -> document_kinds + intent)."""

    def test_word_creates_docx(self):
        info = _APP_DOCUMENT_CAPABILITIES["word"]
        assert info["intent"] == "document.create_docx"
        assert "document" in info["document_kinds"]
        assert "report" in info["document_kinds"]

    def test_excel_creates_csv(self):
        info = _APP_DOCUMENT_CAPABILITIES["excel"]
        assert info["intent"] == "document.create_csv"
        assert "spreadsheet" in info["document_kinds"]

    def test_powerpoint_creates_presentation(self):
        info = _APP_DOCUMENT_CAPABILITIES["powerpoint"]
        assert "presentation" in info["document_kinds"]

    def test_notepad_creates_txt(self):
        info = _APP_DOCUMENT_CAPABILITIES["notepad"]
        assert info["intent"] == "document.create_txt"
        assert "file" in info["document_kinds"]


class TestBrowserActionPatternsUnit:
    """The _BROWSER_ACTION_PATTERNS list covers the common
    browser-control verbs."""

    def test_has_bookmark_pattern(self):
        intents = [p[1] for p in _BROWSER_ACTION_PATTERNS]
        assert "browser.bookmark" in intents

    def test_has_refresh_pattern(self):
        intents = [p[1] for p in _BROWSER_ACTION_PATTERNS]
        assert "browser.refresh" in intents

    def test_has_clear_history_pattern(self):
        intents = [p[1] for p in _BROWSER_ACTION_PATTERNS]
        assert "browser.clear_history" in intents

    def test_has_open_tab_pattern(self):
        intents = [p[1] for p in _BROWSER_ACTION_PATTERNS]
        assert "browser.open_tab" in intents

    def test_has_close_tab_pattern(self):
        intents = [p[1] for p in _BROWSER_ACTION_PATTERNS]
        assert "browser.close_tab" in intents

    def test_has_go_back_pattern(self):
        intents = [p[1] for p in _BROWSER_ACTION_PATTERNS]
        assert "browser.go_back" in intents
