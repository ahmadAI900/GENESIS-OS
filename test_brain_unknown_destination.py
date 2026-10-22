"""Item 18A (L16): process_request could return None (default_response was dead).

`process_request`'s destination chain was if/elif ending at
`elif destination == "ai": ... return answer` with NO final return.
Any destination the router names that is not memory/Internet/
knowledge/ai -- and that is not caught by the greeting/exit/reasoning/
early returns -- fell off the end of the function. process_request
(and `think()`, which forwards to it) then returned None despite the
`-> str` annotation. Reproduced against the committed original:

    process_request -> None
    think           -> None
    default_response-> "I'm not sure about that."

`default_response()` (brain.py) existed for exactly this case and was
referenced by NOTHING in the codebase.

The fix adds a final `return self.default_response()` after the chain,
so unknown destinations land on a real answer. These tests pin:
  - unknown destinations return a str equal to default_response(),
  - every reachable branch (each destination + reasoning + the
    greeting/exit/profile/preference early returns) returns a str,
  - default_response() is actually called by the fallback (no longer
    dead code),
  - structurally, the function's LAST statement is a return -- there
    is no way to fall off the end again.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import pytest

from brain.brain import Brain

MODULE = pathlib.Path("brain") / "brain.py"


def make_brain(route_dest: str, **overrides) -> Brain:
    """A Brain with every collaborator stubbed; only the routing
    decision (and explicit overrides) vary between tests. No real
    AIEngine/MemoryManager is constructed -- the defect under test is
    in process_request's own control flow.
    """
    brain = Brain.__new__(Brain)
    brain.router = SimpleNamespace(route=lambda text: route_dest)
    brain.emotion = SimpleNamespace(detect=lambda text: "neutral")
    brain.memory = SimpleNamespace(
        learn_profile=lambda text: None,
        learn_preference=lambda text: None,
        recall_profile=lambda text: None,
        get_relevent_memory=lambda text: [],
        is_preference_relevant=lambda text: False,
        load_profile=lambda *a: {},
        load_preferences=lambda *a: {},
        save_if_important=lambda text: None,
    )
    brain.internet = SimpleNamespace(search=lambda text: "<html/>")
    brain.parser = SimpleNamespace(extract=lambda raw: {"snippet": "x"})
    brain.formatter = SimpleNamespace(format=lambda parsed: "internet answer")
    brain.knowledge = SimpleNamespace(search=lambda text: None)
    brain.conversation = SimpleNamespace(
        add_user_message=lambda text: None,
        add_assistant_message=lambda answer: None,
        get_recent_history=lambda: [],
    )
    brain.personality = SimpleNamespace(build_context=lambda **kw: "ctx")
    brain.prompt_builder = SimpleNamespace(build_prompt=lambda *a: "prompt")
    brain.ai_engine = SimpleNamespace(generate_response=lambda prompt: "ai answer")
    brain.reasoning = SimpleNamespace(solve=lambda text: "reasoning prompt")
    for name, value in overrides.items():
        setattr(brain, name, value)
    return brain


NEUTRAL_TEXT = "xyzzy plugh"  # not greeting/exit/reasoning/profile/preference


# --------------------------------------------------------------------------
# The regression: unknown destinations must not fall off the end
# --------------------------------------------------------------------------

def test_unknown_destination_returns_the_default_response_not_none():
    brain = make_brain("unknown")

    out = brain.process_request(NEUTRAL_TEXT)

    assert out is not None, (
        "process_request fell off the end of the if/elif chain: an "
        "unknown destination returned None while annotated `-> str`"
    )
    assert isinstance(out, str)
    assert out == brain.default_response(), (
        f"an unknown destination must route through default_response(), "
        f"got {out!r}"
    )


def test_think_forwards_an_unknown_destination_as_a_str():
    """think() is `return self.process_request(...)` -- it inherited
    the same None."""
    brain = make_brain("nowhere")

    out = brain.think(NEUTRAL_TEXT)

    assert isinstance(out, str), f"think() returned {out!r}"
    assert out == brain.default_response()


@pytest.mark.parametrize("destination", [
    "memory",
    # Item 27A (L6): the router names "internet" (lower case); the
    # old "Internet" literal here encoded the case mismatch that made
    # the brain's internet branch dead.
    "internet",
    "knowledge",
    "ai",
    "unknown",
    "surprise_destination",
])
def test_every_destination_branch_returns_a_str(destination):
    brain = make_brain(destination)

    out = brain.process_request(NEUTRAL_TEXT)

    assert isinstance(out, str), (
        f"destination {destination!r} produced {out!r}; every branch "
        "of process_request must return a str"
    )


def test_the_reasoning_branch_returns_a_str():
    # "why" is in is_reasoning_request's keyword list.
    brain = make_brain("unused")

    out = brain.process_request("why is the sky blue")

    assert isinstance(out, str), f"reasoning branch returned {out!r}"


@pytest.mark.parametrize("text,overrides", [
    ("hello", {}),
    ("exit", {}),
    ("my name is Zed", {
        "memory": SimpleNamespace(
            learn_profile=lambda t: "profile response",
            learn_preference=lambda t: None,
        ),
    }),
    ("i prefer tea", {
        "memory": SimpleNamespace(
            learn_profile=lambda t: None,
            learn_preference=lambda t: "preference response",
        ),
    }),
])
def test_the_early_return_branches_return_a_str(text, overrides):
    brain = make_brain("unknown", **overrides)

    out = brain.process_request(text)

    assert isinstance(out, str), f"early return for {text!r} gave {out!r}"


# --------------------------------------------------------------------------
# default_response() must be live code, not a relic
# --------------------------------------------------------------------------

def test_default_response_is_actually_called_by_the_fallback():
    brain = make_brain("unknown")
    calls = []

    def spy_default():
        calls.append("called")
        return "DEFAULT-ANSWER"

    brain.default_response = spy_default

    out = brain.process_request(NEUTRAL_TEXT)

    assert out == "DEFAULT-ANSWER", (
        f"the unknown-destination fallback did not go through "
        f"default_response(): got {out!r}"
    )
    assert calls == ["called"], (
        "default_response() was never invoked; the fix routes "
        "unknown destinations to it"
    )


# --------------------------------------------------------------------------
# Structural: there is no way to fall off the end again
# --------------------------------------------------------------------------

def _function_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "Brain":
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    return node
    raise AssertionError(f"Brain.{name} not found")


def test_process_request_ends_with_a_return():
    """The LAST statement of the body must be a return -- any other
    shape re-opens the fall-off-the-end hole."""
    node = _function_node("process_request")
    assert isinstance(node.body[-1], ast.Return), (
        "process_request no longer ends in a return; an unknown "
        "destination can fall off the end again"
    )


def test_the_fallback_return_goes_through_default_response_and_records_the_item():
    node = _function_node("process_request")
    body = ast.unparse(node)
    assert "return self.default_response()" in body, (
        "process_request does not return default_response() as its "
        "fallback"
    )
    raw = MODULE.read_text(encoding="utf-8-sig").splitlines()
    source = "\n".join(raw[node.lineno - 1: node.end_lineno])
    assert "ITEM 18A" in source, (
        "the fallback does not record Item 18A (L16), so the reason "
        "the final return exists is lost"
    )
