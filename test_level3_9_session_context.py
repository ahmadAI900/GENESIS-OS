"""
Genesis OS — Level 3.9
Session Context Binding.

Verifies handoff section 16 (context/state):

    "Open Chrome."
        ↓
    "Now search YouTube for Python."

The follow-up must be understood as a continuation of the
previous Level 3 turn without repeating the application.
"""

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.session_context import SessionContextBinder


@pytest.fixture()
def binder():
    return SessionContextBinder(WorkflowDecisionEngine())


def _chrome_decision():
    return {
        "level": 3,
        "mode": "os",
        "intent": "application.open",
        "application": "chrome",
        "target": "chrome",
        "confidence": 0.97,
        "parameters": {"operation": "open"},
    }


# =========================================================
# CONTEXT RECORDING
# =========================================================


def test_binder_starts_without_context(binder):
    assert binder.has_context is False
    assert binder.try_rebind("now search youtube for python") is None


def test_strong_level3_decision_is_recorded(binder):
    binder.record_decision(_chrome_decision())
    assert binder.has_context is True


def test_weak_or_non_os_decisions_are_not_recorded(binder):
    binder.record_decision({"level": 1, "mode": "conversation", "confidence": 0.99})
    binder.record_decision({"level": 3, "mode": "os", "intent": "application.open", "confidence": 0.5})

    assert binder.has_context is False


def test_reset_clears_context(binder):
    binder.record_decision(_chrome_decision())
    binder.reset()

    assert binder.has_context is False


# =========================================================
# CONTINUATION REBINDING
# =========================================================


@pytest.mark.parametrize(
    "follow_up,intent",
    [
        ("Now search YouTube for Python.", "browser.search"),
        ("now search youtube for python tutorials", "browser.search"),
        ("then open my downloads folder", "folder.open"),
        ("next find my IELTS essay", "file.search"),
        ("also open excel", "application.open"),
        ("Now find the IELTS file", "file.search"),
    ],
)
def test_contextual_continuations_rebind_to_level3(binder, follow_up, intent):
    binder.record_decision(_chrome_decision())

    decision = binder.try_rebind(follow_up)

    assert decision is not None
    assert decision["level"] == 3
    assert decision["intent"] == intent


def test_youtube_continuation_carries_engine_and_query(binder):
    binder.record_decision(_chrome_decision())

    decision = binder.try_rebind("Now search YouTube for Python.")

    assert decision["parameters"]["engine"] == "youtube"
    assert "python" in decision["parameters"]["query"]


@pytest.mark.parametrize(
    "follow_up",
    [
        "open the first result",
        "click the second link",
        "show the top video",
    ],
)
def test_live_state_anaphora_is_never_faked(binder, follow_up):
    """
    Selecting live browser results requires observing real
    application state; Genesis must decline instead of guessing.
    """
    binder.record_decision(_chrome_decision())

    assert binder.try_rebind(follow_up) is None


@pytest.mark.parametrize(
    "follow_up",
    [
        "now what is an essay",
        "then tell me about IELTS",
        "now that I think about it, explain windows",
    ],
)
def test_conversational_continuations_stay_conversational(binder, follow_up):
    binder.record_decision(_chrome_decision())

    assert binder.try_rebind(follow_up) is None


def test_marker_only_text_declines(binder):
    binder.record_decision(_chrome_decision())

    assert binder.try_rebind("now") is None
    assert binder.try_rebind("and then") is None
