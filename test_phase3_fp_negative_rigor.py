"""
Phase 3 Item 2 -- the vetted negative set and its audit.

This file exists so the negative set cannot quietly rot. A negative
set that is never re-audited drifts back into being the thing it was
built to replace, and its figure stops meaning anything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

import phase3_negatives_vetted_audit as AUDIT
import phase3_negatives_vetted_corpus as CORPUS
from genesis_os.llm_intent_resolver import LLMIntentResolver


class TestComposition:
    def test_at_least_twenty_negatives(self):
        assert len(CORPUS.all_negatives()) >= 20

    def test_every_required_family_is_represented(self):
        families = set(CORPUS.by_category())
        for required in (
            "knowledge_action_adjacent",
            "smalltalk",
            "unexecutable_ambiguity",
            "ambiguous_even_with_context",
            "narration_not_request",
            "advice_not_request",
        ):
            assert required in families, required

    def test_every_item_carries_a_reason(self):
        for item in CORPUS.all_negatives():
            assert item.get("reason"), item["phrase"]

    def test_no_item_declares_an_expectation(self):
        """A negative that expects a capability is not a negative."""
        for item in CORPUS.all_negatives():
            assert not item.get("expect"), item["phrase"]

    def test_prior_carrying_items_exist(self):
        """The Item 4 widening-cost family must not be empty."""
        assert len(CORPUS.with_context()) >= 3


class TestAudit:
    @pytest.fixture(scope="class")
    def report(self):
        return AUDIT.audit()

    def test_audit_passes(self, report):
        assert report["audit_passed"] is True, report

    def test_no_significant_overlap_with_production_surfaces(self, report):
        """Prompts, boundary notes, few-shot examples, gate vocabulary
        and the regex layer must not share a meaningful fragment with
        any negative, or the negatives were written by reading the
        prompts rather than by reasoning about the domain."""
        assert (
            report["overlap_vs_production_surfaces"][
                "items_with_significant_overlap"
            ] == 0
        ), report["overlap_vs_production_surfaces"]["significant"]

    def test_no_overlap_with_either_sealed_corpus(self, report):
        assert report["overlap_vs_sealed_corpora"]["hits"] == []

    def test_no_banned_generator_frame(self, report):
        assert report["banned_frame"]["hits"] == []

    def test_no_internal_duplicates(self, report):
        assert report["internal_duplicates"] == []


class TestVettedNegativesAreDeclinedOffline:
    """Offline half: the deterministic layer must refuse these outright.

    This is the cheap, permanent half of the measurement. The scored
    cloud figure is a one-shot measurement and cannot guard a
    regression; these can. They pin the two known-weak families so a
    future change that makes the regex layer greedier fails here.
    """

    @pytest.fixture
    def engine(self):
        from agents.workflow_decision import WorkflowDecisionEngine

        instance = WorkflowDecisionEngine()
        instance._llm_resolver = None
        return instance

    @pytest.mark.parametrize(
        "phrase",
        [
            "how do I work out compound interest by hand",
            "explain how a hash table resolves collisions",
            "tell me which sorting algorithm is fastest for large "
            "random arrays",
            "walk me through converting a CSV into a spreadsheet by hand",
            "who first described the Krebs cycle",
            "how would you normally rename a variable in a codebase",
            "morning, hope you are having a decent day",
            "thanks, that was genuinely helpful",
            "are you still there",
            "good evening to you",
            "last night I copied the tax documents onto the external drive",
            "the screenshot I took earlier ended up in my downloads folder",
            "what would you do about a spreadsheet with a broken formula",
            "do the needful with the rest of it",
            "deal with the situation however you judge best",
            "make things a bit nicer all round",
        ],
        ids=lambda p: p[:34],
    )
    def test_declined_by_the_regex_layer(self, engine, phrase):
        decision = engine._detect_os_intent(
            engine._normalize_text(phrase)
        )
        assert decision is None, (
            f"the regex layer resolved a negative: {phrase!r} -> "
            f"{decision.get('intent')!r}"
        )

    def test_the_known_failure_shape_is_pinned(self, engine):
        """The one real defect this item found, pinned so it cannot be
        forgotten and so a future fix is measurable.

        A targetless 0.91-confidence `folder.organize` hint is produced
        for ordinary English use of the word "archive", and it is
        RETAINED when the semantic layer declines. Recorded as ledger
        item 21; deliberately not fixed here, because the honest fix
        sits in the arbitration precedence that Item 1 and Item 2
        already settled.
        """
        for phrase in (
            "I already moved the quarterly folder across to the archive "
            "drive yesterday",
            "should I keep the archive folder nested or flat",
        ):
            decision = engine._detect_os_intent(
                engine._normalize_text(phrase)
            )
            assert decision is not None, phrase
            assert decision["intent"] == "folder.organize", phrase
            assert decision.get("target") is None, phrase
            assert decision.get("confidence") == 0.91, phrase

    def test_ambiguous_with_context_stays_unresolved(self, engine):
        """Item 4's widening must not admit any of these.

        The four prior-carrying negatives are the direct test of the
        accepted narrowing documented in the context channel's
        discriminativeness rule. Cloud-scored, all four declined
        (0/4). Offline, the deterministic layer must not resolve them
        either.
        """
        for item in CORPUS.with_context():
            decision = engine._detect_os_intent(
                engine._normalize_text(item["phrase"])
            )
            hint = engine._deterministic_match_is_only_a_hint(
                decision, item["phrase"]
            )
            # Either the layer refuses outright, or it produces a
            # targetless match that the semantic layer is asked to
            # challenge. What it must never do is produce an anchored,
            # decisive match for a request it cannot act on.
            if decision is not None:
                assert hint is True or (
                    decision.get("target") is None
                ), (
                    f"{item['phrase']!r} produced a decisive, anchored "
                    f"match: {decision.get('intent')!r} -> "
                    f"{decision.get('target')!r}"
                )


class TestScorerClassification:
    def test_prior_carrying_negatives_are_still_negatives(self):
        """The remeasurement scorer must NOT file these as context.

        `phase3_final4_score.classify` keys on `prior` and would. These
        items are negatives that happen to carry a prior, so the
        remeasurement classifies on the absence of `expect` instead.
        """
        for item in CORPUS.with_context():
            assert not item.get("expect"), item["phrase"]
            assert item.get("prior"), item["phrase"]

    def test_wilson_interval_is_the_phase3_format(self):
        from phase3_fp_remeasure import wilson

        result = wilson(2, 23)
        assert set(result) == {"pct", "lo", "hi"}
        assert result["pct"] == 8.7
        assert result["lo"] < result["pct"] < result["hi"]
        assert wilson(0, 0) == {"pct": 0.0, "lo": 0.0, "hi": 0.0}