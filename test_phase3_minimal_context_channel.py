"""
Phase 3, Item 4 -- the minimal prior-turn context channel.

WHAT THIS FILE IS
-----------------
Roadmap task 2: "Semantic retrieval and context-aware candidate
selection." Before Item 4 there was NO prior-turn channel anywhere in
the resolution pipeline -- not weak, absent. This file pins the
mechanism that was added and, above all, its blast radius, which is
none.

THE NO-OP GUARANTEE IS THE POINT
--------------------------------
`decide(text)` is the entry point for essentially the whole system.
If supplying a prior turn could perturb requests that have none, this
feature would be a correctness regression dressed as a capability.
So the first half of this file is entirely about proving nothing moved.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No multi-turn session state. No conversation history storage. No
persistent memory. One supplied string, one request, no chain. The
deterministic/regex layer gained no context awareness at all, because
"keywords/regex as fast hints" means exactly that.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

# Every test here is offline: the resolver is driven with ai_engine=None
# or a local probe, so the tier snapshot classifies them as runtime.
pytestmark = pytest.mark.live


# ==================================================================
# 1. NO-OP GUARANTEE
# ==================================================================


def _canonical(decision):
    """A stable rendering of a decision dict, for exact comparison."""
    return json.dumps(decision, sort_keys=True, default=str)


@pytest.fixture
def offline_engine():
    """A decision engine with no model attached.

    Every test in sections 1 and 2 uses this, so the no-op proof is
    about production logic and not about model variability.
    """
    engine = WorkflowDecisionEngine()
    engine._llm_resolver = None
    return engine


def _existing_request_phrases():
    """Every request the sealed corpora and the live suites already use.

    The no-op guarantee is only meaningful if it is checked against the
    requests that actually exist, not a hand-picked few.
    """
    import phase3_v3_corpus as v3
    import phase3_v4_corpus as v4

    phrases = []
    for module in (v3, v4):
        phrases += [item["phrase"] for item in module.all_positives()]
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "phrase" in item:
                        phrases.append(item["phrase"])
    return sorted(set(phrases))


class TestNoOpGuarantee:
    """`decide(text)` must be indistinguishable from before."""

    def test_omitting_prior_turn_is_identical_to_the_one_argument_call(
        self, offline_engine
    ):
        """The parameter is optional and defaults to absent."""
        for phrase in _existing_request_phrases():
            baseline = _canonical(offline_engine.decide(phrase))
            assert _canonical(offline_engine.decide(phrase)) == baseline
            assert _canonical(
                offline_engine.decide(phrase, prior_turn=None)
            ) == baseline, phrase

    @pytest.mark.parametrize(
        "blank", ["", " ", "\t", "\n", "\r\n", "   \n\t  "]
    )
    def test_blank_prior_turns_are_treated_as_absent(
        self, offline_engine, blank
    ):
        """A caller cannot widen the channel by passing whitespace.

        Without this, `"if prior_turn:"`-style truthiness and a
        `str.strip()`-style emptiness check could disagree, and an
        empty string would produce an empty PREVIOUS TURN section in
        the prompt.
        """
        for phrase in _existing_request_phrases():
            baseline = _canonical(offline_engine.decide(phrase))
            assert _canonical(
                offline_engine.decide(phrase, prior_turn=blank)
            ) == baseline, f"{phrase!r} with prior_turn={blank!r}"

    def test_non_string_prior_turns_are_treated_as_absent(
        self, offline_engine
    ):
        """Non-string input is ignored, never coerced into a prompt."""
        for value in (0, 1, False, [], {}, (), object()):
            phrase = "open notepad"
            baseline = _canonical(offline_engine.decide(phrase))
            assert _canonical(
                offline_engine.decide(phrase, prior_turn=value)
            ) == baseline, repr(value)


class TestNoOpPromptsAreByteIdentical:
    """The strongest form of the no-op: the PROMPT is unchanged.

    Comparing decisions can hide a prompt change behind a model that
    happens to answer the same way. These tests compare the prompt
    strings themselves against a transcription of the pre-Item-4
    literal, so a change in wording, spacing or rule numbering is
    caught even if the outcome is unchanged.
    """

    CATALOG = "<<CATALOG>>"
    TEXT = "put the file I just edited into the Reports folder"

    def _capture(self, prior=None):
        resolver = LLMIntentResolver(ai_engine=None)
        captured = {}

        def fake_call(prompt, mode=None):
            captured["prompt"] = prompt
            return json.dumps(
                {"actionable": False, "capability_id": None,
                 "anchor": None}
            )

        resolver._shortlist_catalog = lambda: self.CATALOG
        resolver._capability_catalog = lambda: self.CATALOG
        resolver._backend_modes = lambda: ("cloud",)
        resolver._call_llm_with_timeout = fake_call
        resolver._grounding_probe(
            self.TEXT, deadline=float("inf"),
            **({"prior_turn": prior} if prior else {}),
        )
        return captured["prompt"]

    def test_grounding_prompt_without_prior_is_unchanged(self):
        """Transcription of the pre-Item-4 `_grounding_probe` literal."""
        catalog = self.CATALOG
        text = self.TEXT
        original = (
            "You are deciding whether a user is asking an "
            "assistant to CONTROL A COMPUTER, or merely talking.\n\n"
            f"CAPABILITY INDEX:\n{catalog}\n\n"
            "Rules:\n"
            "1. If the user is talking, joking, asking a "
            "knowledge question, requesting creative writing, "
            "or asking for advice, reply actionable=false.\n"
            "2. If the user wants the assistant to perform an "
            "action on their computer, device, files, "
            "applications or accounts, reply actionable=true "
            "and give the single best capability id.\n"
            "3. Quote a span of the user's message VERBATIM that "
            "shows why. Copy it exactly, including the user's own "
            "spelling. Do not paraphrase, do not translate, do not "
            "invent words that are not there.\n"
            "4. If the request is indirect or informal, still "
            "answer true if it genuinely asks for a computer "
            "action.\n\n"
            'Reply ONLY with JSON: {"actionable": true|false, '
            '"capability_id": "<id or null>", '
            '"anchor": "<verbatim span or null>"}\n\n'
            f"USER: {text}\n\n"
            "JSON:"
        )
        assert self._capture() == original

    def test_grounding_prompt_with_prior_adds_only_the_context(self):
        prior = "The quarterly revenue table is open in a browser."
        prompt = self._capture(prior=prior)
        assert f"PREVIOUS TURN: {prior}\n\n" in prompt
        assert f"USER: {self.TEXT}\n\nJSON:" in prompt
        # The original rule numbering is preserved and extended, never
        # renumbered, so the model is not re-trained mid-prompt.
        assert "3. Quote a span of the user's CURRENT REQUEST" in prompt
        assert "Never quote from the PREVIOUS TURN." in prompt

    def test_single_stage_prompt_is_unchanged_without_prior(self):
        without = LLMIntentResolver._build_prompt(self.TEXT, "CAT")
        assert "PREVIOUS TURN" not in without
        assert without.endswith(f'\n\nREQUEST: "{self.TEXT}"\n\nJSON:')

    def test_single_stage_prompt_gains_context_when_supplied(self):
        prior = "A folder called invoices is open in explorer."
        with_prior = LLMIntentResolver._build_prompt(
            self.TEXT, "CAT", prior_turn=prior
        )
        assert f"PREVIOUS TURN: {prior}" in with_prior
        assert "PREVIOUS TURN" not in LLMIntentResolver._build_prompt(
            self.TEXT, "CAT"
        )


# ==================================================================
# 2. NO CONTEXT IS EVER INVENTED
# ==================================================================


class TestNoInventedContext:
    """A request with no prior turn must not behave as if one existed."""

    def test_prior_block_helper_is_empty_for_every_absent_form(self):
        for value in (None, "", "   ", "\n", 0, [], {}):
            assert LLMIntentResolver._prior_turn_block(value) == "", value

    def test_prior_block_helper_labels_only_real_context(self):
        block = LLMIntentResolver._prior_turn_block(
            "  a folder called invoices is open  "
        )
        assert block == "PREVIOUS TURN: a folder called invoices is open\n\n"

    def test_discriminativeness_is_not_widened_without_a_prior_turn(self):
        """The dangerous direction: a request that used to FAIL
        grounding must still fail, identically, with no prior turn."""
        # The whole request as the anchor leaves nothing outside it.
        for request, anchor in (
            ("shut it", "shut it"),
            ("do that for me", "do that for me"),
            ("handle it somehow", "handle it somehow"),
        ):
            bare = LLMIntentResolver.evaluate_grounding(
                request, "application.close", anchor
            )
            assert bare.grounded is False, request
            assert any(
                "discriminates nothing" in reason
                for reason in bare.reasons
            ), (request, bare.reasons)

    def test_a_vague_request_is_not_rescued_by_an_unrelated_prior(self):
        """A prior turn must not rescue a request that has no anchor
        content of its own. Substance is still required."""
        result = LLMIntentResolver.evaluate_grounding(
            "it", "application.close", "it",
            prior_turn="the terminal and the settings window are open",
        )
        assert result.grounded is False
        assert any(
            "no content word" in reason for reason in result.reasons
        ), result.reasons

    def test_prior_turn_cannot_satisfy_fidelity(self):
        """Fidelity is NOT relaxed.

        MEASURED 2026-10-04: against all 8 sealed v4 context items the
        model anchored on the current request in 8/8 cases, never on
        the prior turn. So allowing a prior-turn anchor would buy
        nothing while giving up the guarantee that the model points at
        words the user just typed. This pins that decision.
        """
        result = LLMIntentResolver.evaluate_grounding(
            "shut it",
            "application.close",
            "the settings window",           # quoted from the prior
            prior_turn="the settings window is open",
        )
        assert result.grounded is False
        assert any(
            "not present in the request" in reason
            for reason in result.reasons
        ), result.reasons


# ==================================================================
# 3. ANCHOR FIDELITY UNDER CONTEXT  (roadmap step 3)
# ==================================================================


class TestDiscriminativenessUnderContext:
    """Only discriminativeness changes, and only when a prior exists."""

    def test_whole_request_anchor_fails_without_a_prior(self):
        """The pre-Item-4 rule, unchanged."""
        result = LLMIntentResolver.evaluate_grounding(
            "shut it down please", "application.close",
            "shut it down please",
        )
        assert result.grounded is False
        assert any(
            "discriminates nothing" in reason
            for reason in result.reasons
        ), result.reasons

    def test_same_anchor_passes_with_a_prior_that_supplies_the_rest(self):
        """The measured situation: a short request has no honest
        narrower span, so the prior turn carries the discrimination."""
        result = LLMIntentResolver.evaluate_grounding(
            "shut it down please",
            "application.close",
            "shut it down please",
            prior_turn="the settings window is currently open",
        )
        assert result.discriminative is True, result.reasons
        # Everything else still has to hold.
        assert result.fidelity is True
        assert result.substance is True
        assert result.grounded is True, result.reasons

    def test_a_blank_prior_does_not_widen_the_gate(self):
        result = LLMIntentResolver.evaluate_grounding(
            "shut it down please", "application.close",
            "shut it down please", prior_turn="    ",
        )
        assert result.discriminative is False
        assert result.grounded is False

    def test_a_prior_of_pure_stopwords_does_not_widen_the_gate(self):
        """The prior must contribute CONTENT. A prior made only of
        function words must not make a whole-request anchor
        discriminative, or context grounding would be trivially
        gameable."""
        result = LLMIntentResolver.evaluate_grounding(
            "shut it down please", "application.close",
            "shut it down please",
            prior_turn="it is that one over there and they are here",
        )
        assert result.discriminative is False, result.reasons
        assert result.grounded is False

    def test_known_narrowing_is_documented_not_hidden(self):
        """The accepted trade-off, pinned as executable documentation.

        With a prior turn present, a model that names the WRONG
        capability and quotes the whole request can still pass
        discriminativeness, because the prior supplies the
        out-of-anchor content word. That is a real narrowing of the
        guarantee, accepted because without it no context item can
        ever ground, and bounded because it cannot arise when no prior
        is supplied.

        Closing it properly needs the capability to be checked against
        the prior turn -- per-capability verifiers, or a model-side
        agreement check. Both are out of scope for this item. This test
        exists so the narrowing is a stated, executable fact rather
        than an accident, and so that if a later item closes it, this
        test fails and the documentation is updated.
        """
        wrong_capability_still_grounds = (
            LLMIntentResolver.evaluate_grounding(
                "shut it down please",
                "file.delete",                     # wrong on purpose
                "shut it down please",
                prior_turn="the settings window is currently open",
            )
        )
        assert wrong_capability_still_grounds.grounded is True, (
            "the accepted narrowing no longer holds; if this now "
            "fails, a later item may have closed it and this "
            "documentation should be updated"
        )

        # And the same shape with NO prior is still refused.
        without_prior = LLMIntentResolver.evaluate_grounding(
            "shut it down please", "file.delete", "shut it down please",
        )
        assert without_prior.grounded is False

    def test_a_lexical_tier_gate_could_not_replace_this_rule(self):
        """Why the narrowing is not simply tightened with the tier.

        Recorded because it was measured, not assumed. The obvious
        tightening -- "the prior may only widen discriminativeness when
        the request is lexically ACTIONABLE" -- does not work: the
        legitimate context cases that need the prior are AMBIGUOUS, and
        so are the illegitimate ones. Tiers do not separate them, so
        the model's own actionable judgement remains the primary
        defence and the lexical layer cannot be substituted for it.
        """
        needs_prior = [
            "get rid of it",
            "fix that",
            "scrape the figures out of that",
            "shut it down please",
            "put a duplicate of it on the desktop",
        ]
        ambiguous_but_legitimate = [
            phrase for phrase in needs_prior
            if LLMIntentResolver.lexical_actionability(phrase)
            == LLMIntentResolver.AMBIGUOUS
        ]
        assert ambiguous_but_legitimate, (
            "expected at least one legitimate context case to sit in "
            "the AMBIGUOUS tier"
        )


# ==================================================================
# 4. SYNTHETIC CONTEXT CASES
# ==================================================================


def _engine_answering(capability_id, anchor):
    """A real engine whose grounding probe returns a fixed answer.

    Only the MODEL PROBE is stubbed. `evaluate_grounding`, the
    capability registry, the safety layer and the control plane are the
    real implementations, so these cases exercise the real
    admissibility policy rather than a mock of it.
    """
    engine = WorkflowDecisionEngine()
    real = LLMIntentResolver(ai_engine=None)

    class _Probe:
        def __init__(self):
            self.calls = []

        def __call__(self, text, deadline, prior_turn=None):
            self.calls.append((text, prior_turn))
            return {
                "actionable": True,
                "capability_id": capability_id,
                "anchor": anchor,
            }

    probe = _Probe()
    real._grounding_probe = probe
    real.lexical_actionability = staticmethod(
        lambda text: real.AMBIGUOUS
    )
    real._backend_modes = lambda: ("cloud",)
    real._call_llm_with_timeout = lambda prompt, mode=None: "{}"
    engine._llm_resolver = real
    return engine, real, probe


def _engine_declining():
    """A real engine whose model declines to ground.

    This is the realistic path for a request that stays ambiguous even
    with a prior turn: the model says the request is not a computer
    action. The registry, safety layer, resolver and control plane are
    all real; only the model's answer is fixed.
    """
    engine = WorkflowDecisionEngine()
    real = LLMIntentResolver(ai_engine=None)

    class _Decline:
        def __init__(self):
            self.calls = []

        def __call__(self, text, deadline, prior_turn=None):
            self.calls.append((text, prior_turn))
            return {
                "actionable": False,
                "capability_id": None,
                "anchor": None,
            }

    probe = _Decline()
    real._grounding_probe = probe
    real.lexical_actionability = staticmethod(
        lambda text: real.AMBIGUOUS
    )
    real._backend_modes = lambda: ("cloud",)
    real._call_llm_with_timeout = lambda prompt, mode=None: "{}"
    engine._llm_resolver = real
    return engine, real, probe


# The five synthetic cases. SYNTHETIC on purpose: no sealed-corpus
# phrase appears here, and the sealed-phrase guards in
# test_phase3_semantic_grounding.py and
# test_phase3_cross_domain_arbitration.py enforce that mechanically.
CONTEXT_CASES = [
    (
        "pronoun reference",
        "the settings window is open right now",
        "get rid of it",
        "application.close",
    ),
    (
        "elided reference",
        "I am looking at a spreadsheet called budget.xlsx",
        "put a duplicate of it on the desktop",
        "file.copy",
    ),
    (
        "definite reference across two candidates",
        "notepad and the terminal are both open",
        "shut the first one",
        "application.close",
    ),
    (
        "anaphoric continuation",
        "the screen is much too bright in here",
        "fix that",
        "display.brightness_set",
    ),
    (
        "object reference to a browser page",
        "the quarterly revenue table is open in a browser window",
        "scrape the figures out of that",
        "browser.extract",
    ),
]

CASE_IDS = [case[0] for case in CONTEXT_CASES]
# The anchor is the WHOLE request in every case. That is not laziness:
# it is what the model actually returned in 8/8 sealed v4 probes
# (see the discriminativeness note in llm_intent_resolver), and it is
# the situation the context channel exists to handle.
CASE_ROWS = [
    (case[1], case[2], case[3], case[2]) for case in CONTEXT_CASES
]


class TestSyntheticContextCases:
    """Five context-dependent cases, all synthetic, all offline."""

    @pytest.mark.parametrize(
        "prior,phrase,capability,anchor", CASE_ROWS, ids=CASE_IDS,
    )
    def test_context_grounding_resolves_the_capability(
        self, prior, phrase, capability, anchor
    ):
        engine, resolver, probe = _engine_answering(capability, anchor)
        result = resolver.grounded_capability(
            phrase, require_ambiguous_tier=False, prior_turn=prior
        )
        assert result is not None, (
            f"grounding refused a context-dependent request; "
            f"reasons={getattr(result, 'reasons', None)}"
        )
        assert result.capability_id == capability
        # The prior really did reach the prompt.
        assert probe.calls
        assert probe.calls[-1][1] == prior

    @pytest.mark.parametrize(
        "prior,phrase,capability,anchor", CASE_ROWS, ids=CASE_IDS,
    )
    def test_the_same_case_is_refused_without_the_prior_turn(
        self, prior, phrase, capability, anchor
    ):
        """Each case is context-DEPENDENT, not merely context-tolerated.

        Without the prior turn the identical model answer must be
        refused, because the whole-request anchor discriminates
        nothing. This is what makes these cases evidence about the
        channel rather than about the regex layer.
        """
        engine, resolver, probe = _engine_answering(capability, anchor)
        assert resolver.grounded_capability(
            phrase, require_ambiguous_tier=False
        ) is None, (
            "resolved WITHOUT context, so this case does not "
            "demonstrate the context channel"
        )

    @pytest.mark.parametrize(
        "prior,phrase,capability,anchor", CASE_ROWS, ids=CASE_IDS,
    )
    def test_no_prior_means_no_context_reaches_the_prompt(
        self, prior, phrase, capability, anchor
    ):
        """Not one of these cases may leak a prior into the prompt
        when none was supplied."""
        engine, resolver, probe = _engine_answering(capability, anchor)
        resolver.grounded_capability(
            phrase, require_ambiguous_tier=False
        )
        assert probe.calls
        assert all(call[1] is None for call in probe.calls), probe.calls


class TestGenuinelyAmbiguousEvenWithContext:
    """At least one case that must FAIL gracefully, not wrongly.

    Two independent kinds of failure are pinned here, because they fail
    for different reasons and only one is under this item's control:

    * STRUCTURAL refusals -- the grounding contract itself rejects the
      answer (no substance, broken fidelity, unregistered capability).
      Deterministic, and cannot be talked past.
    * MODEL refusals -- the model declines to treat the request as a
      computer action at all. This is the realistic outcome for a
      request that stays ambiguous, and it is the primary defence
      against over-acceptance; see the accepted-narrowing note in
      ``TestDiscriminativenessUnderContext``.
    """

    # --- structural refusals -------------------------------------

    def test_anchor_without_content_word_is_refused(self):
        """A prior turn cannot supply the missing substance."""
        result = LLMIntentResolver.evaluate_grounding(
            "it", "application.close", "it",
            prior_turn="the terminal and the settings window are open",
        )
        assert result.grounded is False
        assert any(
            "no content word" in reason for reason in result.reasons
        ), result.reasons

    def test_a_prior_naming_no_registered_capability_still_declines(self):
        """Grounding must not manufacture an answer from thin air."""
        result = LLMIntentResolver.evaluate_grounding(
            "do the needful",
            "no.such.capability.at.all",
            "do the needful",
            prior_turn="I was thinking about the weather earlier",
        )
        assert result.grounded is False

    def test_a_rejected_capability_is_not_rescued_by_context(self):
        result = LLMIntentResolver.evaluate_grounding(
            "do the needful", "not.a.capability", "do the needful",
            prior_turn="a folder called invoices is open in explorer",
        )
        assert result.grounded is False
        assert result.reasons

    # --- model refusals ------------------------------------------

    def test_a_request_still_ambiguous_with_context_is_declined(self):
        """The prior names a file but the request names no action.

        "and then do the usual thing" plus "the quarterly report is on
        my desktop somewhere" gives the model nothing to resolve: the
        request says no operation. The correct behaviour is to decline,
        and to do so quietly -- no capability, no Level 3 decision.
        """
        engine, resolver, probe = _engine_declining()
        prior = "the quarterly report is on my desktop somewhere"
        assert resolver.grounded_capability(
            "and then do the usual thing",
            require_ambiguous_tier=False,
            prior_turn=prior,
        ) is None
        # The prior really was offered, so this is a considered
        # decline rather than the channel never being used.
        assert probe.calls[-1][1] == prior

    def test_declining_with_context_stays_level_1_end_to_end(self):
        engine, resolver, probe = _engine_declining()
        decision = engine.decide(
            "and then do the usual thing",
            prior_turn="the quarterly report is on my desktop somewhere",
        )
        assert decision["level"] != 3, decision
        assert not decision.get("intent"), decision

    def test_conversation_with_a_prior_is_still_conversation(self):
        """Context must not make chit-chat actionable."""
        engine, resolver, probe = _engine_declining()
        decision = engine.decide(
            "that genuinely cheered me up",
            prior_turn="we opened the settings window earlier",
        )
        assert decision["level"] != 3, decision
        assert not decision.get("intent"), decision
        assert probe.calls, "the prior should still have been offered"


# ==================================================================
# 5. SCOPE BOUNDARIES
# ==================================================================


class TestChannelReachabilityLimit:
    """Where `decide()` actually consults the context channel.

    MEASURED live 2026-10-04, cloud `openai/gpt-oss-120b`. This is a
    statement about the ROUTING that reaches the channel, not about
    the channel itself.

    `decide()` only consults the prior-aware semantic path when
    `_deterministic_match_is_only_a_hint` is true, and that returns
    False for a `None` decision. So a request with no deterministic
    candidate reaches the prior-aware channel only via the AMBIGUOUS
    escalation in `_grounded_os_decision`, which by design fires on
    lexically AMBIGUOUS wording only.

    Consequence: an ACTIONABLE-tier request with no deterministic
    candidate never reaches the context channel at all. Two of the
    eight sealed v4 context items are in that class, and they were
    observed resolving to Level 1 both with and without a prior turn.

    Changing this means changing the hint gate or adding a new
    prior-aware escalation -- a production routing change, which is
    explicitly out of scope for a context-channel item. It is
    recorded as a named future item instead, and pinned here so the
    limit cannot be forgotten.
    """

    def test_no_deterministic_candidate_is_not_a_hint(self):
        engine, _, _ = _engine_declining()
        assert engine._deterministic_match_is_only_a_hint(
            None, "skip this one"
        ) is False

    def test_actionable_tier_does_not_reach_the_grounding_channel(self):
        """The structural reason, asserted rather than described."""
        assert LLMIntentResolver.lexical_actionability(
            "skip this one"
        ) == LLMIntentResolver.ACTIONABLE
        assert LLMIntentResolver.lexical_actionability(
            "pull the numbers out of that"
        ) == LLMIntentResolver.AMBIGUOUS

    def test_ambiguous_tier_does_reach_the_context_channel(self):
        """The working half, end to end, with the prior honoured."""
        engine, resolver, probe = _engine_answering(
            "browser.extract", "pull the numbers out of that"
        )
        decision = engine.decide(
            "pull the numbers out of that",
            prior_turn="The quarterly revenue table is open in the browser.",
        )
        assert decision["level"] == 3, decision
        assert decision["intent"] == "browser.extract", decision
        assert any(call[1] for call in probe.calls), (
            "the prior-aware probe should have been reached"
        )


class TestScopeBoundaries:
    """What the channel must NOT have become."""

    def test_the_deterministic_layer_has_no_context_parameter(self):
        """The regex layer gained nothing. It has no mechanism for
        this and must not grow one: 'keywords/regex as fast hints'
        depends on it staying context-free."""
        import inspect

        signature = inspect.signature(
            WorkflowDecisionEngine._detect_os_intent
        )
        assert "prior" not in str(signature), signature

    def test_decide_does_not_store_or_accumulate_prior_turns(self):
        """One string, one request. No history, no memory, no chain."""
        engine = WorkflowDecisionEngine()
        engine._llm_resolver = None
        engine.decide(
            "open notepad", prior_turn="a folder called x is open"
        )
        engine.decide(
            "shut it", prior_turn="another prior entirely"
        )
        stored = [
            name for name in vars(engine)
            if "prior" in name.lower() or "history" in name.lower()
            or "context_items" in name.lower()
        ]
        assert stored == [], stored

    def test_arbitration_probe_remains_prior_unaware(self):
        """Arbitration is done and out of scope for this item.

        Its anchor-fidelity rule was specified for single-turn
        requests. Widening it belongs to whatever item revisits
        arbitration, not to a context channel.
        """
        import inspect

        signature = inspect.signature(
            LLMIntentResolver.arbitration_probe
        )
        assert "prior" not in str(signature), signature

    def test_arbitrate_capabilities_remains_prior_unaware(self):
        import inspect

        signature = inspect.signature(
            LLMIntentResolver.arbitrate_capabilities
        )
        assert "prior" not in str(signature), signature

    def test_precondition_enforcement_is_untouched_by_this_item(self):
        """Item 3's mechanism must be exactly as it was.

        Checked on the identifier, not the word "prior": the
        enforcement comment legitimately contains the English word
        "prior-state" when explaining that no precondition in the
        registry is a prior-state condition.
        """
        import inspect

        from genesis_os import capability_resolver

        source = inspect.getsource(
            capability_resolver.CapabilityResolver._resolve_exact
        )
        assert "prior_turn" not in source
        assert "_prior_turn_block" not in source
