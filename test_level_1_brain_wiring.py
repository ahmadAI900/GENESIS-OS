"""Directive 8A: Level 1 conversation must reach the real brain.

Before Item 8A, `GenesisRuntime._handle_level_1` probed
`self.conversation` for `.respond()` and then for `.chat()`.
`ConversationEngine` defines NEITHER, so both `hasattr` checks were
false on every single call and the method returned

    {"message": "Level 1 conversation pipeline is connected."}

for every conversation-classified request, having asked the brain
nothing at all. Genesis answered a greeting with a sentence about its
own plumbing.

These tests pin the fixed behaviour:
  * a brain whose `process_request` returns a sentinel MUST surface
    that sentinel through `_handle_level_1`;
  * a brain WITHOUT `process_request` MUST fall back without crashing;
  * the brain MUST actually be consulted (the before-state never was);
  * the turn MUST be recorded on the conversation engine when it can;
  * the degraded answer MUST NOT claim the pipeline is connected.
"""

from __future__ import annotations

import pytest

from conversation.conversation import ConversationEngine
from runtime.genesis_runtime import GenesisRuntime

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

SENTINEL = "BRAIN-SENTINEL-ANSWER"


class SpyBrain:
    """A brain that answers with a sentinel and records its calls."""

    def __init__(self, answer=SENTINEL):
        self.calls = []
        self._answer = answer

    def process_request(self, text):
        self.calls.append(text)
        return self._answer


class BrainWithoutProcessRequest:
    """A brain-shaped object missing the method the runtime needs."""

    def think(self, text):
        return "should never be reached"


class RaisingBrain:
    def process_request(self, text):
        raise RuntimeError("brain exploded")


def make_runtime(brain, conversation=None):
    return GenesisRuntime(
        brain=brain,
        conversation=conversation,
        memory=None,
        ai_engine=None,
        agent_bridge=None,
    )


# =====================================================================
# The fix
# =====================================================================

def test_brain_answer_surfaces_through_handle_level_1():
    """The sentinel must reach the caller. Fails before Item 8A, which
    returned the placeholder dict instead of ever calling the brain."""
    brain = SpyBrain()
    runtime = make_runtime(brain)

    result = runtime._handle_level_1("hello there", {"memories": []})

    assert result["response"] == SENTINEL, result
    assert result["pipeline"] == "LEVEL_1", result
    assert result["success"] is True, result


def test_the_brain_is_actually_consulted():
    """The before-state never called it. This is the direct regression."""
    brain = SpyBrain()
    runtime = make_runtime(brain)

    runtime._handle_level_1("what is my name", None)

    assert brain.calls == ["what is my name"], (
        "the brain was not consulted with the user's text"
    )


def test_memory_context_still_flows_through():
    """The fix must not disturb the memory envelope."""
    brain = SpyBrain()
    runtime = make_runtime(brain)
    memory = {"memories": ["user likes tea"], "count": 1}

    result = runtime._handle_level_1("hello", memory)

    assert result["memory"] == memory, result


def test_the_turn_is_recorded_on_the_conversation_engine():
    brain = SpyBrain()
    conversation = ConversationEngine()
    runtime = make_runtime(brain, conversation)

    runtime._handle_level_1("remember this", None)

    history = conversation.get_history()
    texts = [
        entry.get("message") if isinstance(entry, dict) else entry
        for entry in history
    ]
    assert "remember this" in texts, history
    assert SENTINEL in texts, history
    roles = [
        entry.get("role") for entry in history if isinstance(entry, dict)
    ]
    assert roles == ["user", "assistant"], history


def test_a_conversation_engine_without_recorders_does_not_crash():
    """Recording is optional; the answer must survive without it."""
    brain = SpyBrain()
    runtime = make_runtime(brain, conversation=object())

    result = runtime._handle_level_1("hello", None)

    assert result["response"] == SENTINEL, result


def test_a_brain_whose_recorder_raises_still_returns_the_answer():
    """History is a convenience, not the answer."""

    class ExplodingConversation:
        def add_user_message(self, text):
            raise RuntimeError("history is down")

        def add_assistant_message(self, text):
            raise RuntimeError("history is down")

    brain = SpyBrain()
    runtime = make_runtime(brain, ExplodingConversation())

    result = runtime._handle_level_1("hello", None)

    assert result["response"] == SENTINEL, result


# =====================================================================
# Graceful degradation -- must never raise
# =====================================================================

def test_a_brain_without_process_request_falls_back_without_crashing():
    brain = BrainWithoutProcessRequest()
    runtime = make_runtime(brain)

    result = runtime._handle_level_1("hello", None)

    assert result["success"] is True, result
    response = result["response"]
    assert isinstance(response, dict), response
    assert response["available"] is False, response


def test_no_brain_at_all_falls_back_without_crashing():
    runtime = make_runtime(None)

    result = runtime._handle_level_1("hello", None)

    assert result["success"] is True, result
    assert result["response"]["available"] is False, result


def test_a_raising_brain_falls_back_without_crashing():
    runtime = make_runtime(RaisingBrain())

    result = runtime._handle_level_1("hello", None)

    assert result["success"] is True, result
    assert result["response"]["available"] is False, result


def test_the_degraded_answer_never_claims_the_pipeline_is_connected():
    """The old placeholder said the pipeline WAS connected while
    consulting nothing. The degraded answer must state the truth."""
    for brain in (None, BrainWithoutProcessRequest(), RaisingBrain()):
        response = make_runtime(brain)._handle_level_1("hi", None)["response"]
        assert "is connected" not in response["message"], response


# =====================================================================
# The real classes really do disagree with the old probe
# =====================================================================

def test_conversation_engine_really_defines_neither_phantom_method():
    """Documents why the old hasattr() chain could never fire. If a
    future change ADDS .respond/.chat to ConversationEngine, this test
    tells us to revisit the runtime rather than silently leaving two
    competing answers."""
    engine = ConversationEngine()
    assert not hasattr(engine, "respond"), (
        "ConversationEngine now defines respond(); the Item 8A rationale "
        "has changed and the runtime should be re-examined"
    )
    assert not hasattr(engine, "chat"), (
        "ConversationEngine now defines chat(); the Item 8A rationale has "
        "changed and the runtime should be re-examined"
    )