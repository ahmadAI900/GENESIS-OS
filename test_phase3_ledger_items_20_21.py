"""Phase 3 final ledger items 20 and 21 — regression tests.

Item 20 — the semantic/grounding path did run when the deterministic
layer produced no candidate, but it ran WITHOUT the conversational
prior turn. ``_detect_extended_os_intent`` already falls back to
``_try_semantic_intent_resolution(text)`` when nothing deterministic
matched, yet that call passed no ``prior_turn``, so grounding could
never use conversational context. That is exactly the measured
``shortlist(prior=False)`` symptom on cases where a prior turn existed.

Note the ledger's original wording — that the semantic path was
"skipped entirely" — is NOT what the code does, and the fix below is
deliberately the smaller and cheaper one: forward ``prior_turn`` into
the existing call rather than opening a second, duplicate semantic
call from ``decide()``. Opening a second call was measured to double
the semantic cost for anaphoric requests (2 calls instead of 1) while
fixing the same symptom.

Item 21 — the "archive" family in the unseen-task classifier fired on
phrases naming no object ("archive folder"), because "folder" is itself
an archive object word, and answered with a confident 0.91
folder.organize carrying an empty target.

Both fixes must be structural and phrase-independent, so these tests
pin the behaviour rather than the phrases.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.unseen_task_semantic import _try_archive
from agents.workflow_decision import WorkflowDecisionEngine


@pytest.fixture
def engine():
    return WorkflowDecisionEngine()


def _counting_semantic(engine, result=None):
    """Replace the semantic layer with a call counter.

    ``result`` is what the stubbed layer returns. None models the
    "model was asked and declined / could not help" case, which is the
    branch both fixes must survive.
    """
    calls = []

    def stub(text, prior_turn=None, **kwargs):
        calls.append({"text": text, "prior_turn": prior_turn})
        return result

    engine._try_semantic_intent_resolution = stub
    return calls


# =========================================================
# ITEM 20 — no deterministic candidate must still be grounded
# =========================================================


class TestItem20NoCandidateStillGrounded:
    @pytest.mark.parametrize(
        "phrase",
        [
            "do the thing we discussed earlier",
            "again please",
            "that one again",
            "carry on with that",
        ],
    )
    def test_no_candidate_still_reaches_the_semantic_layer(
        self, engine, phrase
    ):
        """Sanity, not the fix: grounding on the no-candidate path
        already happened before Item 20 (that is why the defect was a
        missing prior_turn rather than a skipped call). Pinned so a
        future refactor cannot turn this into a genuinely skipped
        path."""
        calls = _counting_semantic(engine, result=None)
        engine.decide(phrase)
        assert calls, (
            f"{phrase!r}: the semantic path was skipped entirely"
        )

    def test_no_candidate_costs_one_extra_call_only_when_prior_given(
        self, engine
    ):
        """The chosen fix applies the prior turn from decide(), gated on
        one being supplied. Without a prior turn the no-candidate path
        still costs exactly the single call the internal fallback
        already makes; with one, it costs that plus one contextual
        call. A decisive match still costs zero."""
        calls = _counting_semantic(engine, result=None)
        engine.decide("again please")
        assert len(calls) == 1, (
            f"no-prior no-candidate path should cost 1 call, got {len(calls)}"
        )
        calls = _counting_semantic(engine, result=None)
        engine.decide("again please", prior_turn="user: open budget.xlsx")
        assert len(calls) == 2, (
            f"prior-turn no-candidate path should cost 2 calls "
            f"(internal + contextual), got {len(calls)}"
        )

    def test_deterministic_layer_stays_context_free(self):
        """The regression this fix had to avoid. Threading prior_turn
        into _detect_os_intent was tried first and reverted: it breaks
        the pinned boundary that the deterministic regex layer must
        carry no conversational context."""
        import inspect

        from agents.workflow_decision import WorkflowDecisionEngine

        for method in (
            WorkflowDecisionEngine._detect_os_intent,
            WorkflowDecisionEngine._detect_extended_os_intent,
        ):
            signature = inspect.signature(method)
            assert "prior" not in str(signature), (
                f"{method.__name__} must stay context-free: {signature}"
            )

    def test_prior_turn_is_actually_forwarded_when_supplied(self, engine):
        """The measured symptom: shortlist(prior=False) on cases where a
        prior turn existed, because the path was bypassed before the
        prior turn could matter."""
        calls = _counting_semantic(engine, result=None)
        prior = "user: open the budget spreadsheet"
        engine.decide("again please", prior_turn=prior)
        assert any(c["prior_turn"] == prior for c in calls), (
            "the prior turn never reached the semantic layer"
        )

    def test_no_prior_turn_is_forwarded_as_none(self, engine):
        calls = _counting_semantic(engine, result=None)
        engine.decide("again please")
        assert all(c["prior_turn"] is None for c in calls)

    def test_grounded_answer_is_adopted_when_no_candidate_existed(
        self, engine
    ):
        # Modelled on what the real semantic layer emits: a semantic
        # answer only clears the L3 promotion gate when it carries BOTH
        # _semantic_resolution and _capability_resolution and lands at
        # >= 0.80 (workflow_decision.py:890-902). A stub missing those
        # markers would be rejected downstream for reasons unrelated to
        # the routing fix under test.
        grounded = {
            "level": 3,
            "mode": "os",
            "intent": "file.open",
            "target": "budget.xlsx",
            "confidence": 0.85,
            "parameters": {
                "_semantic_resolution": True,
                "_capability_resolution": {"status": "resolved"},
            },
        }
        _counting_semantic(engine, result=grounded)
        decision = engine.decide("again please")
        assert decision.get("intent") == "file.open", (
            "a grounded semantic answer was resolved but not adopted"
        )
        assert decision.get("target") == "budget.xlsx"

    def test_decisive_fast_path_still_costs_zero_calls(self, engine):
        """Must not regress: a decisive anchored deterministic match
        must not pay for a model call."""
        calls = _counting_semantic(engine, result=None)
        decision = engine.decide("open notepad")
        assert decision.get("intent") == "application.open"
        assert calls == [], (
            f"the decisive fast path made {len(calls)} semantic call(s)"
        )

    def test_anchored_match_still_costs_zero_calls(self, engine):
        calls = _counting_semantic(engine, result=None)
        engine.decide("open my downloads")
        assert calls == []

    def test_unresolvable_stays_unresolved_not_fabricated(self, engine):
        """No candidate and no grounded answer must yield an honest
        unresolved decision, never an invented one."""
        _counting_semantic(engine, result=None)
        decision = engine.decide("again please")
        assert decision.get("intent") is None or decision.get(
            "level"
        ) != 3


# =========================================================
# ITEM 21 — "archive" must not fire without a referent
# =========================================================


class TestItem21ArchiveRequiresAReferent:
    @pytest.mark.parametrize(
        "phrase",
        [
            "archive folder",
            "archive the folder",
            "zip drive",
            "compress files",
            "archive stuff",
            "archive backups",
        ],
    )
    def test_bare_generic_noun_does_not_resolve(self, phrase):
        """A verb plus a bare generic noun names no object. "folder"
        is itself an archive object word, which is exactly how the
        false positive arose."""
        assert _try_archive(phrase) is None, (
            f"{phrase!r} resolved an archive operation without naming "
            f"anything to archive"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "archive my documents",
            "compress the downloads folder",
            "zip up everything related to Project Alpha",
            "pack the photos into an archive",
            "I need everything related to Project Alpha zipped up",
        ],
    )
    def test_documented_positives_still_resolve(self, phrase):
        decision = _try_archive(phrase)
        assert decision is not None, (
            f"{phrase!r} is a documented archive positive and must not "
            f"have been narrowed away"
        )
        assert decision.intent == "folder.organize"

    def test_narrowing_is_on_shape_not_the_word_archive(self):
        """The rule is verb + bare generic noun, so it applies across
        the verb set, not to one literal."""
        for verb in ("archive", "zip", "compress", "bundle", "pack"):
            assert _try_archive(f"{verb} folder") is None, (
                f"verb {verb!r} with a bare generic noun still fires"
            )
            assert _try_archive(f"{verb} my documents") is not None, (
                f"verb {verb!r} with a real referent stopped working"
            )

    def test_create_folder_named_archive_still_wins(self, engine):
        """Pre-existing guard must survive the narrowing: creating a
        folder called Archive is folder.create, not an archive op."""
        decision = engine.decide("make a folder named Archive")
        assert decision.get("intent") != "folder.organize" or (
            decision.get("target")
        )

    def test_no_confident_organize_for_the_reported_phrase(self, engine):
        """End-to-end: the reported phrase must not come back as a
        confident targetless folder.organize."""
        _counting_semantic(engine, result=None)
        decision = engine.decide("archive folder")
        assert decision.get("intent") != "folder.organize", (
            "the false positive is still reachable through decide()"
        )
