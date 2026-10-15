"""
Regression test for the multi-agent response-formatting bug.

Bug:
    After ``ResultAggregator.aggregate(results)`` returned the
    wrapper dict ``{'success', 'agent_count', 'results', 'summary'}``,
    ``run_multi_agent`` passed that entire wrapper dict to
    ``synthesize_multi_agent_results`` as its ``results`` argument.
    Because the synthesis function expects a *list* of agent result
    dicts (``[{'agent', 'result'}, ...]``), the
    ``isinstance(results, list)`` branch was skipped, the synthesis
    prompt was never built, and the fallback ``_extract_response``
    returned ``str(wrapper_dict)`` -- a raw Python dict printed
    straight to the user as ``Genesis: {'success': True, ...}``.

Fix:
    ``run_multi_agent`` now passes ``aggregated['results']`` (the
    inner list of agent result dicts) to
    ``synthesize_multi_agent_results``.

These tests assert:

1. ``synthesize_multi_agent_results`` returns a non-empty string
   when given a list of agent result dicts shaped like the
   aggregator's inner payload (the natural-language path is
   actually entered, not the dict-string fallback).
2. The string is not the ``str()`` of a dict (no curly-brace
   dict-as-string leaking to the user).
3. The end-to-end ``run_multi_agent`` call site hands the inner
   list (not the wrapper dict) to the synthesis function. This is
   the regression the live crash uncovered.
"""
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real GenesisOS.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


def _make_agent_result(agent_name, response_text):
    return {
        "agent": agent_name,
        "result": {
            "response": response_text,
            "success": True,
            "metadata": {},
        },
    }


def test_synthesize_returns_natural_language_for_list_input(
    monkeypatch,
):

    from genesis import GenesisOS

    g = GenesisOS()

    monkeypatch.setattr(
        g.brain,
        "think",
        lambda prompt: "Here is a coherent research summary.",
    )

    agent_results = [
        _make_agent_result(
            "Research Agent",
            "Biology is the study of life ...",
        ),
        _make_agent_result(
            "Document Agent",
            "I can help you save this as a document.",
        ),
    ]

    response = g.synthesize_multi_agent_results(
        "research biology and save it as a pdf",
        agent_results,
    )

    assert isinstance(response, str), (
        "synthesis must return a string, got "
        f"{type(response).__name__}"
    )
    assert response.strip(), "synthesis must not return an empty string"
    assert not response.startswith("{"), (
        "synthesis must not return the str() of a dict; "
        f"got: {response[:120]!r}"
    )


def test_synthesize_fallback_also_returns_string_for_list_input(
    monkeypatch,
):

    from genesis import GenesisOS

    g = GenesisOS()

    def raise_in_synthesis(prompt):
        raise RuntimeError("synthesis LLM unavailable")

    monkeypatch.setattr(
        g.brain,
        "think",
        raise_in_synthesis,
    )

    agent_results = [
        _make_agent_result(
            "Research Agent",
            "Biology is the study of life ...",
        ),
        _make_agent_result(
            "Document Agent",
            "I can help you save this as a document.",
        ),
    ]

    response = g.synthesize_multi_agent_results(
        "research biology and save it as a pdf",
        agent_results,
    )

    assert isinstance(response, str)
    assert not response.startswith("{"), (
        "fallback must not return the str() of a dict; "
        f"got: {response[:200]!r}"
    )


def test_run_multi_agent_call_site_passes_inner_list_to_synthesis(
    monkeypatch,
):

    from genesis import GenesisOS

    g = GenesisOS()

    executor_results = [
        {
            "step": 1,
            "agent": "Research Agent",
            "result": {
                "response": "biology findings",
                "success": True,
            },
            "status": "completed",
        },
        {
            "step": 2,
            "agent": "Document Agent",
            "result": {
                "response": "I can help save it as a document",
                "success": True,
            },
            "status": "completed",
        },
    ]

    monkeypatch.setattr(
        g.executor,
        "execute",
        lambda tasks: executor_results,
    )

    captured = {}

    def fake_synthesize(self, user_request, results):
        captured["user_request"] = user_request
        captured["results"] = results
        captured["type"] = type(results).__name__
        return "synthesized natural-language response"

    monkeypatch.setattr(
        GenesisOS,
        "synthesize_multi_agent_results",
        fake_synthesize,
    )

    classification = {
        "level": 2,
        "mode": "multi_agent",
        "agents": ["Research Agent", "Document Agent"],
    }

    final = g.run_multi_agent(
        "research biology and save it as a pdf",
        classification,
    )

    assert final == "synthesized natural-language response"

    assert captured["user_request"] == (
        "research biology and save it as a pdf"
    )

    assert captured["type"] == "list", (
        "run_multi_agent must pass the inner list of agent "
        "results (aggregated['results']) to the synthesis "
        "function, not the wrapper dict. Got: "
        f"{captured['type']}"
    )

    assert isinstance(captured["results"], list)
    assert len(captured["results"]) == 2

    for item in captured["results"]:
        assert isinstance(item, dict)
        assert "agent" in item
        assert "result" in item
