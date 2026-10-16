"""Directive 8B: synthesis must actually call the AI engine.

Before Item 8B, `GenesisRuntime._synthesize` probed `self.ai_engine`
for `.generate()` and then for `.chat()`. `AIEngine` defines NEITHER --
its real public method is `generate_response(prompt) -> str` at
`ai/ai_engine.py:239`. Both `hasattr` checks were therefore false, the
`try` block completed without doing anything, and the method fell
through to `return agent_result`.

The user therefore received the raw agent payload where a
natural-language Genesis answer belonged, with no synthesis performed
and no error reported. Because the AttributeError never even arose
(the methods were probed with hasattr first), nothing was logged either.

These tests pin the fixed behaviour:
  * `generate_response` MUST be called with the synthesis prompt and
    its answer MUST surface;
  * the prompt MUST still carry the task, agent results and memory;
  * an engine that raises MUST fall back to `agent_result`;
  * an engine without the method MUST fall back without crashing;
  * nothing may fabricate a synthesized answer.
"""

from __future__ import annotations

import pytest

from conversation.conversation import ConversationEngine
from runtime.genesis_runtime import GenesisRuntime

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

SENTINEL = "AI-SYNTHESIZED-SENTINEL"


class SpyAI:
    """An AI engine that records prompts and answers with a sentinel."""

    def __init__(self, answer=SENTINEL):
        self.prompts = []
        self._answer = answer

    def generate_response(self, prompt):
        self.prompts.append(prompt)
        return self._answer


class RaisingAI:
    def __init__(self):
        self.calls = 0

    def generate_response(self, prompt):
        self.calls += 1
        raise RuntimeError("provider exploded")


class AIWithoutGenerateResponse:
    """The shape the old code was written against."""

    def generate(self, prompt):
        return "phantom generate"

    def chat(self, prompt):
        return "phantom chat"


def make_runtime(ai_engine):
    return GenesisRuntime(
        brain=None,
        conversation=ConversationEngine(),
        memory=None,
        ai_engine=ai_engine,
        agent_bridge=None,
    )


AGENT_RESULT = {"success": True, "findings": ["three rows found"]}


# =====================================================================
# The fix
# =====================================================================

def test_synthesized_answer_surfaces():
    """Fails before Item 8B, which returned AGENT_RESULT verbatim."""
    engine = SpyAI()

    result = make_runtime(engine)._synthesize(
        "summarise the sheet", AGENT_RESULT, None
    )

    assert result == SENTINEL, result


def test_the_ai_engine_is_actually_called_once():
    """The before-state never called it at all."""
    engine = SpyAI()

    make_runtime(engine)._synthesize(
        "summarise the sheet", AGENT_RESULT, None
    )

    assert len(engine.prompts) == 1, engine.prompts


def test_the_prompt_still_carries_task_results_and_memory():
    """The prompt must be preserved, not replaced with a stub."""
    engine = SpyAI()
    memory = {"memories": ["user prefers metric units"]}

    make_runtime(engine)._synthesize(
        "convert the units", AGENT_RESULT, memory
    )

    prompt = engine.prompts[0]
    assert "convert the units" in prompt, prompt
    assert "three rows found" in prompt, prompt
    assert "user prefers metric units" in prompt, prompt
    assert "You are Genesis" in prompt, prompt


# =====================================================================
# Failure paths -- must fall back, never fabricate
# =====================================================================

def test_a_raising_engine_falls_back_to_agent_result():
    engine = RaisingAI()

    result = make_runtime(engine)._synthesize(
        "summarise", AGENT_RESULT, None
    )

    assert result == AGENT_RESULT, result
    assert engine.calls == 1, "it must have tried before giving up"


def test_an_engine_without_generate_response_falls_back_without_crashing():
    result = make_runtime(AIWithoutGenerateResponse())._synthesize(
        "summarise", AGENT_RESULT, None
    )

    assert result == AGENT_RESULT, result


def test_no_engine_at_all_falls_back_without_crashing():
    result = make_runtime(None)._synthesize(
        "summarise", AGENT_RESULT, None
    )

    assert result == AGENT_RESULT, result


def test_synthesis_never_fabricates_an_answer_on_failure():
    """A failed synthesis must surface the raw result, not an
    invented summary dressed up as one."""
    for engine in (RaisingAI(), AIWithoutGenerateResponse(), None):
        result = make_runtime(engine)._synthesize(
            "summarise", AGENT_RESULT, None
        )
        assert result is AGENT_RESULT or result == AGENT_RESULT, result


# =====================================================================
# The real class really disagrees with the old probe
# =====================================================================

def test_ai_engine_really_defines_neither_phantom_method():
    """Documents why the old hasattr() chain could never fire."""
    from ai.ai_engine import AIEngine

    assert "generate_response" in AIEngine.__dict__, (
        "AIEngine.generate_response moved; re-examine _synthesize"
    )
    assert "generate" not in AIEngine.__dict__, (
        "AIEngine now defines generate(); the Item 8B rationale has "
        "changed and the runtime should be re-examined"
    )
    assert "chat" not in AIEngine.__dict__, (
        "AIEngine now defines chat(); the Item 8B rationale has changed "
        "and the runtime should be re-examined"
    )