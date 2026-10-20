"""Item 20C (R9): L2 samples must classify as L2, not be promoted to L3.

THE HOLE (reproduced fail-before)
---------------------------------
The benchmark harness (benchmark/real_e2e.py) measured 3/16 failures:
the three L2 samples came back as Level 3

    "Research the latest AI safety papers."   expected L2 Research
    "Study biology with me."                  expected L2 Study
    "Analyze this spreadsheet for outliers."  expected L2 Data

Ground truth: the SAMPLES are right and the system misclassifies.
With the LLM resolver disabled, the very same engine routes all three
to the correct Level 2 agents (Research Agent / Study Agent / Data
Agent), and GENESIS_MASTER_COMPLETION documents "Research X" as an
L2 Research Agent task.

The mechanism: decide()'s promotion gate returns a model-origin
decision (parameters._semantic_resolution + _capability_resolution,
confidence >= 0.80) BEFORE the conversational guard and the L2 agent
detectors ever run. The LLM proposes web.research / spreadsheet.read
for phrasings the deterministic layer classifies as L2 work, and the
proposal wins by construction.

THE FIX
--------
A semantic-origin (model-proposed) OS decision must not outrank the
L2 ownership check: when the deterministic L2 detectors claim the
text, the gate declines to promote and falls through to the existing
L2/L1 machinery. Deterministic L3 promotions (regex confidence >=
0.90) are untouched, and so are semantic proposals for text no L2
agent owns -- those still promote.
"""

from __future__ import annotations

import pytest

from genesis_os.capability_registry import CapabilityRegistry

# (prompt, expected agent-name fragment) -- the three measured
# benchmark failures, per benchmark/real_e2e.py SAMPLES.
L2_SAMPLES = [
    pytest.param(
        "Research the latest AI safety papers.",
        "research",
        id="research-ai-safety-papers",
    ),
    pytest.param(
        "Study biology with me.",
        "study",
        id="study-biology",
    ),
    pytest.param(
        "Analyze this spreadsheet for outliers.",
        "data",
        id="analyze-spreadsheet-outliers",
    ),
]

# Capability proposed for each L2 sample, as the production LLM would.
# resolve() receives the NORMALIZED text (lowercased, punctuation
# trimmed), so matching is by substring, never by the raw sample.


def _proposed_capability(lowered: str):
    if "research" in lowered or "biology" in lowered:
        return "web.research"
    if "outliers" in lowered or "spreadsheet" in lowered:
        return "spreadsheet.read"
    if "create a text file" in lowered:
        return "document.create_txt"
    return None


class _StubResolver:
    """A stand-in for LLMIntentResolver.resolve, proposing a real
    registered capability with confidence 0.85 -- the shape the
    production LLM path produces (then stamped with
    _semantic_resolution by _try_semantic_intent_resolution and
    _capability_resolution by the control plane)."""

    def __init__(self):
        self.calls = []

    def resolve(self, text, **kwargs):
        self.calls.append(text)
        cap = _proposed_capability(text.lower())
        if cap is None:
            # Knowledge questions and anything else the model would
            # decline: the resolver must never be what makes these
            # samples change level.
            return None
        parameters = {"requires_target": True}
        descriptor = CapabilityRegistry.get(cap)
        if descriptor is not None:
            for name in descriptor.preconditions:
                parameters[name] = f"stub {name}"
        return {
            "operation": cap,
            "target": cap.split(".", 1)[0],
            "parameters": parameters,
            "confidence": 0.85,
        }

    def grounded_capability(self, text, **kwargs):
        # Grounding declines; promotion must be judged with and
        # without this hook present, never because of it.
        return None


@pytest.fixture
def genesis_with_stub(genesis_runtime):
    """The real GenesisOS (registry + decision engine) with only the
    LLM resolver replaced. Restored for every other test."""
    workflow_decision = genesis_runtime.workflow_decision
    saved = getattr(workflow_decision, "_llm_resolver", None)
    stub = _StubResolver()
    workflow_decision._llm_resolver = stub
    try:
        yield genesis_runtime, stub
    finally:
        workflow_decision._llm_resolver = saved


@pytest.mark.parametrize("text,agent_fragment", L2_SAMPLES)
def test_l2_sample_is_not_promoted_to_l3(
    genesis_with_stub, text, agent_fragment
):
    """Fail-before: the promotion gate returned L3 for these."""
    g, stub = genesis_with_stub

    decision = g.classify(text)

    # decide() normalizes before calling the resolver, so compare
    # against the normalized form (lowercased, punctuation-trimmed).
    normalized = text.lower().strip(".! ").strip()
    assert any(normalized in call for call in stub.calls), (
        f"the stub resolver was never asked for {text!r} "
        f"(calls={stub.calls!r}), so this test would not reproduce "
        "the measured failure path"
    )
    assert decision.get("level") == 2, (
        f"{text!r} classified as L{decision.get('level')}/"
        f"{decision.get('mode')} (intent={decision.get('intent')!r}); "
        "a model proposal outranked the L2 ownership check"
    )
    assert decision.get("mode") in {"single_agent", "multi_agent"}
    agent = (decision.get("agent") or "").lower()
    assert agent_fragment in agent, (
        f"expected an L2 {agent_fragment!r} agent, got "
        f"{decision.get('agent')!r}"
    )


def test_deterministic_l3_promotion_is_untouched(
    genesis_with_stub,
):
    """Regex-confidence promotions carry no model marker and must
    keep working with the stub attached (green before and after)."""
    g, _stub = genesis_with_stub

    open_chrome = g.classify("open chrome")
    assert open_chrome.get("level") == 3
    assert open_chrome.get("intent") == "application.open"

    web = g.classify("search the web for python tutorials")
    assert web.get("level") == 3
    assert web.get("intent") == "web.research"


def test_semantic_l3_promotion_survives_when_no_l2_agent_owns_the_text(
    genesis_with_stub,
):
    """The decline is narrow: a model proposal for text that is NOT
    L2-owned still promotes. This sample is deterministic-L1 (the
    lexical layer has no file-creation regex for it) and only the
    semantic path can reach L3 -- green before and after."""
    g, stub = genesis_with_stub

    decision = g.classify(
        "create a text file named notes.txt with a shopping list"
    )

    assert any(
        "create a text file" in call for call in stub.calls
    ), (
        "the semantic path was not exercised; nothing proved the "
        "narrow decline"
    )
    parameters = decision.get("parameters") or {}
    assert parameters.get("_semantic_resolution") is True, (
        "this L3 must come from the semantic path"
    )
    assert decision.get("level") == 3, (
        f"semantic L3 regressed to L{decision.get('level')}/"
        f"{decision.get('mode')}: the decline is wider than "
        "L2-owned text"
    )


def test_l1_stays_l1_with_the_stub_attached(genesis_with_stub):
    """Control: attaching a resolver does not drag knowledge
    questions out of Level 1 (green before and after)."""
    g, _stub = genesis_with_stub

    decision = g.classify("What is photosynthesis?")

    assert decision.get("level") == 1
