"""
ITEM 18B (L17) — keyword matching must sit on word boundaries.

agents/workflow_decision.py matched routing keywords with a raw
substring test (`keyword in text`), so the short design keyword "ui"
fired inside ordinary words ("build", "circuit", "guide", "quick")
and spuriously selected the design agent. The fix compiles a
\\b-anchored, re.escape'd pattern per keyword (cached), so a
standalone token still matches while inside-of-a-word hits do not.

Behavior pinned here:
  * "build a website" and friends do NOT select design (was: did).
  * "make a ui mockup" still selects design (both versions).
  * single-agent detection inherits the same result.
  * multi-word phrase keywords ("market analysis", "class ") still
    match exactly as before.
  * the match site is not a raw substring test.
"""
from inspect import getsource
from types import SimpleNamespace

import agents.workflow_decision as workflow_decision_module
from agents.workflow_decision import WorkflowDecisionEngine

ALL_AGENTS = [
    "research",
    "coding",
    "study",
    "internet",
    "document",
    "design",
    "business",
    "data",
    "planning",
    "security",
]

FALSE_POSITIVE_TEXTS = {
    "build a website": "ui inside 'build'",
    "solve this circuit puzzle": "ui inside 'circuit'",
    "read the guide": "ui inside 'guide'",
    "quick question": "ui inside 'quick'",
}


def engine():
    return WorkflowDecisionEngine(
        registry=SimpleNamespace(
            get_all_agents=lambda: list(ALL_AGENTS)
        )
    )


def test_build_a_website_does_not_select_design():
    matches = engine()._detect_multi_agents("build a website")

    assert "design" not in matches, (
        "'build a website' selected design via 'ui' "
        "inside 'build'"
    )


def test_make_a_ui_mockup_still_selects_design():
    matches = engine()._detect_multi_agents("make a ui mockup")

    assert "design" in matches


def test_circuit_does_not_select_design():
    matches = engine()._detect_multi_agents(
        "solve this circuit puzzle"
    )

    assert "design" not in matches


def test_guide_does_not_select_design():
    matches = engine()._detect_multi_agents("read the guide")

    assert "design" not in matches


def test_quick_does_not_select_design():
    matches = engine()._detect_multi_agents("quick question")

    assert "design" not in matches


def test_false_positive_texts_match_no_agent_at_all():
    for text in FALSE_POSITIVE_TEXTS:
        matches = engine()._detect_multi_agents(text)

        assert matches == [], (
            f"{text!r} -> {matches!r}; expected no agent "
            f"({FALSE_POSITIVE_TEXTS[text]})"
        )


def test_single_agent_is_none_for_build_a_website():
    single = engine()._detect_single_agent("build a website")

    assert single is None


def test_single_agent_still_found_for_ui_mockup():
    single = engine()._detect_single_agent("make a ui mockup")

    assert single == "design"


def test_design_keyword_still_matches_word():
    matches = engine()._detect_multi_agents("design a logo")

    assert "design" in matches


def test_graphic_keyword_still_matches_word():
    matches = engine()._detect_multi_agents(
        "create a graphic banner"
    )

    assert "design" in matches


def test_multiword_phrase_keyword_still_matches():
    matches = engine()._detect_multi_agents("run a market analysis")

    assert "business" in matches


def test_marketplace_word_does_not_select_business():
    matches = engine()._detect_multi_agents("the marketplace is big")

    assert "business" not in matches


def test_trailing_space_keyword_still_matches():
    matches = engine()._detect_multi_agents("write a class Foo")

    assert "coding" in matches


def test_multi_agent_detection_still_aggregates():
    matches = engine()._detect_multi_agents(
        "research papers about ui design"
    )

    assert set(matches) == {"research", "design"}


def test_single_agent_is_none_when_two_agents_match():
    single = engine()._detect_single_agent(
        "research papers about ui design"
    )

    assert single is None


def test_match_site_is_not_a_raw_substring_test():
    source = getsource(
        WorkflowDecisionEngine._detect_multi_agents
    )

    assert "if keyword in text:" not in source
    assert "_keyword_pattern(keyword).search(text)" in source


def test_keyword_pattern_helper_is_boundary_anchored_and_cached():
    helper = getattr(
        workflow_decision_module, "_keyword_pattern", None
    )

    assert helper is not None, (
        "workflow_decision._keyword_pattern is missing"
    )

    first = helper("ui")
    second = helper("ui")

    assert first is second, "compiled patterns are not cached"
    assert first.search("build a website") is None
    assert first.search("make a ui mockup") is not None
    assert first.search("circuit") is None
