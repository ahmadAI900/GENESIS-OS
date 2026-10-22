"""Item 27A (L6): the brain's Internet/knowledge branches were unreachable.

Two separate breaks in the brain -> router -> internet chain:

1. CASE MISMATCH. router/router.py returned the destination "internet"
   (lower case) while brain/brain.py compared ``destination ==
   "Internet"`` (capital I). The comparison could never be true, so the
   whole internet branch was dead code: a routed internet query fell
   through to the AI branch and the real search never ran.

2. NO KNOWLEDGE DESTINATION. The router never named "knowledge" at all
   (it only ever returned memory/internet/ai), so brain's knowledge
   branch could never fire either -- Knowledge.search was called from
   nowhere in the chain.

The fix introduces ONE shared vocabulary of destinations
(router/destinations.py) imported by BOTH sides, so the two cannot
drift apart again, and gives the router a knowledge destination so the
knowledge branch is reachable.

These tests pin:
  * one shared vocabulary, imported by router and brain,
  * brain carries no hard-coded destination literal any more,
  * the router names the internet destination for an internet query,
  * the router names the knowledge destination for a knowledge query,
  * an internet query really reaches the brain's internet branch,
  * a knowledge query really reaches the brain's knowledge branch,
  * the knowledge branch returns a str (Knowledge.search returns a LIST
    of result dicts -- returning it raw broke the -> str contract).
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

from brain.brain import Brain
from router.router import Router

BRAIN_MODULE = pathlib.Path("brain") / "brain.py"
ROUTER_MODULE = pathlib.Path("router") / "router.py"

INTERNET_QUERY = "search the web for the latest python release notes"
KNOWLEDGE_QUERY = "search my documents for the invoice"


def make_brain(router, **overrides):
    """A Brain with every collaborator stubbed; only the router is
    the real one, so the whole chain is exercised.
    """
    brain = Brain.__new__(Brain)
    brain.router = router
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
    brain.internet = SimpleNamespace(search=lambda text: {})
    brain.parser = SimpleNamespace(extract=lambda raw: {})
    brain.formatter = SimpleNamespace(format=lambda parsed: "internet answer")
    brain.knowledge = SimpleNamespace(search=lambda text: [])
    brain.conversation = SimpleNamespace(
        add_user_message=lambda text: None,
        add_assistant_message=lambda answer: None,
        get_recent_history=lambda: [],
    )
    brain.personality = SimpleNamespace(build_context=lambda **kw: "ctx")
    brain.prompt_builder = SimpleNamespace(build_prompt=lambda *a: "prompt")
    brain.ai_engine = SimpleNamespace(
        generate_response=lambda prompt: "ai answer"
    )
    brain.reasoning = SimpleNamespace(solve=lambda text: "reasoning prompt")
    for name, value in overrides.items():
        setattr(brain, name, value)
    return brain


# --------------------------------------------------------------------------
# One shared vocabulary
# --------------------------------------------------------------------------

def test_router_and_brain_import_one_shared_destination_vocabulary():
    brain_src = BRAIN_MODULE.read_text(encoding="utf-8-sig")
    router_src = ROUTER_MODULE.read_text(encoding="utf-8-sig")

    assert "from router.destinations import" in brain_src, (
        "brain/brain.py does not import the shared destination "
        "vocabulary -- the two sides can drift apart again"
    )
    assert "from router.destinations import" in router_src, (
        "router/router.py does not import the shared destination "
        "vocabulary"
    )


def test_the_shared_vocabulary_defines_every_destination():
    from router import destinations

    assert destinations.DEST_MEMORY == "memory"
    assert destinations.DEST_INTERNET == "internet"
    assert destinations.DEST_KNOWLEDGE == "knowledge"
    assert destinations.DEST_AI == "ai"
    assert set(destinations.ALL_DESTINATIONS) == {
        "memory",
        "internet",
        "knowledge",
        "ai",
    }


def test_brain_has_no_hardcoded_destination_literals():
    """The bug WAS a literal mismatch. Brain must compare against the
    shared constants, never against a typed-out string.
    """
    tree = ast.parse(BRAIN_MODULE.read_text(encoding="utf-8-sig"))
    literals = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "destination"
        ):
            for comparator in node.comparators:
                if (
                    isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, str)
                ):
                    literals.add(comparator.value)

    assert not literals, (
        f"brain/brain.py compares `destination` against hard-coded "
        f"literals {sorted(literals)} -- use the shared constants "
        f"(router/destinations.py) instead"
    )


# --------------------------------------------------------------------------
# The router must be able to NAME both destinations
# --------------------------------------------------------------------------

def test_router_names_the_internet_destination_for_an_internet_query():
    assert Router().route(INTERNET_QUERY) == "internet"


def test_router_names_the_knowledge_destination_for_a_knowledge_query():
    assert Router().route(KNOWLEDGE_QUERY) == "knowledge"


def test_router_only_ever_returns_a_known_destination():
    from router import destinations

    router = Router()
    for text in [
        INTERNET_QUERY,
        KNOWLEDGE_QUERY,
        "my name is Zed",
        "hello there",
        "write me a poem about rain",
    ]:
        assert router.route(text) in destinations.ALL_DESTINATIONS, (
            f"route({text!r}) returned an unknown destination"
        )


# --------------------------------------------------------------------------
# Both branches must be REACHABLE from the brain
# --------------------------------------------------------------------------

def test_an_internet_query_reaches_the_internet_branch():
    calls = []

    def fake_search(text):
        calls.append(("internet.search", text))
        return {"title": "Release notes", "content": "c", "url": "u"}

    def fake_format(parsed):
        calls.append(("formatter.format", parsed))
        return "internet answer"

    brain = make_brain(
        Router(),
        internet=SimpleNamespace(search=fake_search),
        formatter=SimpleNamespace(format=fake_format),
    )

    out = brain.process_request(INTERNET_QUERY)

    assert ("internet.search", INTERNET_QUERY) in calls, (
        "the internet branch was never entered: internet.search was "
        f"not called (calls: {calls!r})"
    )
    assert any(name == "formatter.format" for name, _ in calls), (
        "the internet branch did not format the parsed result"
    )
    assert isinstance(out, str)
    assert out == "internet answer"


def test_a_knowledge_query_reaches_the_knowledge_branch():
    calls = []

    def fake_knowledge_search(text):
        calls.append(("knowledge.search", text))
        return [
            {
                "path": "notes.md",
                "score": 1.0,
                "snippet": "the invoice total is 42",
            }
        ]

    brain = make_brain(
        Router(),
        knowledge=SimpleNamespace(search=fake_knowledge_search),
    )

    out = brain.process_request(KNOWLEDGE_QUERY)

    assert ("knowledge.search", KNOWLEDGE_QUERY) in calls, (
        "the knowledge branch was never entered: Knowledge.search was "
        f"not called (calls: {calls!r})"
    )
    assert isinstance(out, str), (
        f"the knowledge branch returned {out!r}; process_request is "
        "annotated `-> str` and Knowledge.search returns a LIST"
    )
    assert "42" in out, (
        f"the knowledge result was not surfaced in the answer: {out!r}"
    )


def test_an_empty_knowledge_result_still_returns_a_str():
    brain = make_brain(
        Router(),
        knowledge=SimpleNamespace(search=lambda text: []),
    )

    out = brain.process_request(KNOWLEDGE_QUERY)

    assert isinstance(out, str)
    assert "knowledge base" in out.lower()
