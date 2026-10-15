from agents.workflow_decision import WorkflowDecisionEngine


def engine():
    return WorkflowDecisionEngine()


def test_ordinary_is_sentence_is_not_os():
    decision = engine().decide(
        'the topic is "develop countries uses more fuel"'
    )

    assert decision["level"] != 3
    assert decision["intent"] != "application.inspect"


def test_word_count_is_not_word_application():
    decision = engine().decide(
        "the word count should be between 250 and 280"
    )

    assert decision["level"] != 3
    assert decision["application"] != "word"


def test_ielts_essay_is_not_os():
    decision = engine().decide(
        """
        write an IELTS essay on the topic
        develop countries uses more fuel.
        The word count should be between 250 and 280.
        """
    )

    assert decision["level"] != 3


def test_open_chrome_is_os():
    decision = engine().decide(
        "open chrome"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.open"
    assert decision["application"] == "chrome"


def test_launch_vscode_is_os():
    decision = engine().decide(
        "launch vscode"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.open"
    assert decision["application"] == "vscode"


def test_close_chrome_is_os():
    decision = engine().decide(
        "close chrome"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.close"
    assert decision["application"] == "chrome"


def test_inspect_chrome_is_os():
    decision = engine().decide(
        "inspect chrome"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


def test_chrome_running_is_os():
    decision = engine().decide(
        "is chrome running?"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


def test_normal_question_is_not_os():
    decision = engine().decide(
        "is this IELTS sentence correct?"
    )

    assert decision["level"] != 3


def test_run_code_is_not_application_open():
    decision = engine().decide(
        "run this Python code"
    )

    assert decision["level"] != 3


def test_execute_function_is_not_application_open():
    decision = engine().decide(
        "execute this function"
    )

    assert decision["level"] != 3


def test_word_meaning_is_not_application_inspection():
    decision = engine().decide(
        "what does the word mean?"
    )

    assert decision["level"] != 3


# =====================================================
# ROADMAP TASK 4 — DETERMINISTIC MATCHES ARE FAST HINTS
# =====================================================
# The final3 taxonomy showed 10 held-out requests where the
# keyword/regex layer answered instantly and the semantic layer
# was never consulted, so a model that would have chosen correctly
# never got the chance. These tests pin the structural rule that
# fixes it.
#
# Every case here is SYNTHETIC and written to exercise the
# mechanism (an unanchored match inside a multi-member capability
# family), never the specific phrases that exposed the bug.


def _det_intent(intent, **extra):
    """A bare deterministic L3 decision, as the regex layer emits."""
    decision = {
        "level": 3,
        "mode": "os",
        "task": "synthetic probe",
        "agent": None,
        "agents": [],
        "intent": intent,
        "application": None,
        "target": None,
        "parameters": {},
        "confidence": 0.95,
        "reason": "synthetic",
    }
    decision.update(extra)
    return decision


def _semantic_intent(intent, confidence=0.85):
    """A semantic decision, carrying both provenance markers."""
    return {
        "level": 3,
        "mode": "os",
        "task": "synthetic probe",
        "agent": None,
        "agents": [],
        "intent": intent,
        "application": None,
        "target": None,
        "parameters": {
            "_semantic_resolution": True,
            "_capability_resolution": {
                "status": "resolved",
                "resolved": True,
            },
        },
        "confidence": confidence,
        "reason": "synthetic",
    }


def test_unanchored_match_alone_is_not_enough():
    """Being unanchored in a multi-member family does NOT by itself
    make a match a hint. With no lexical evidence either way, the
    deterministic answer stands and no model call is paid. Only a
    CONTRADICTED family triggers the override."""
    eng = engine()

    # Every media capability scores 0.0 against this text, so
    # nothing contradicts media.play_pause.
    assert not eng._deterministic_match_is_only_a_hint(
        _det_intent("media.play_pause"), "unrelated request text"
    )


def test_missing_request_text_treats_the_match_as_a_hint():
    """With nothing to arbitrate against, ask the model rather than
    silently trusting the hint."""
    eng = engine()

    assert eng._deterministic_match_is_only_a_hint(
        _det_intent("media.play_pause")
    )


def test_uncontradicted_family_match_is_not_a_hint():
    """The safety clause. A hint that IS its own family's best
    lexical match must be left alone, otherwise the model can
    overwrite a correct deterministic answer. This is the case
    that broke the pinned Phase 0 guard for "write hello world"
    when every unanchored match was treated as a hint."""
    eng = engine()

    # No gui sibling describes "write hello world" better than
    # gui.type_text does, so the hint stands and no model call is
    # paid.
    assert not eng._deterministic_match_is_only_a_hint(
        _det_intent("gui.type_text"), "write hello world"
    )


def test_contradicted_family_match_is_a_hint():
    """The motivating case: media.previous describes this request
    far better than the play_pause hint."""
    eng = engine()

    assert eng._deterministic_match_is_only_a_hint(
        _det_intent("media.play_pause"),
        "go back to the previous track",
    )


def test_anchored_match_is_not_a_hint():
    eng = engine()

    # A named object anchors the match, so it stays on the fast
    # path and is not sent to the model.
    assert not eng._deterministic_match_is_only_a_hint(
        _det_intent("file.delete", target="report.pdf"), "x y"
    )
    assert not eng._deterministic_match_is_only_a_hint(
        _det_intent("application.open", application="chrome"), "x y"
    )


def test_already_semantic_match_is_not_a_hint():
    eng = engine()

    # Consulting again would loop.
    assert not eng._deterministic_match_is_only_a_hint(
        _semantic_intent("media.previous"), "x y"
    )


def test_non_capability_and_empty_decisions_are_not_hints():
    eng = engine()

    assert not eng._deterministic_match_is_only_a_hint(None, "x y")
    assert not eng._deterministic_match_is_only_a_hint(
        "not a decision", "x y"
    )
    assert not eng._deterministic_match_is_only_a_hint(
        _det_intent(None), "x y"
    )
    assert not eng._deterministic_match_is_only_a_hint(
        _det_intent("bareword"), "x y"
    )


def test_semantic_layer_overrules_a_plausible_but_wrong_hint():
    """The defect itself: a wrong unanchored family guess used to
    win outright. The semantic answer must now survive to L3."""
    eng = engine()

    eng._detect_os_intent = lambda text: _det_intent(
        "media.play_pause"
    )
    eng._resolve_with_capability_control_plane = (
        lambda decision: decision
    )
    eng._try_semantic_intent_resolution = (
        lambda text: _semantic_intent("media.previous")
    )

    decision = eng.decide("go back to the previous track")

    assert decision["level"] == 3
    assert decision["intent"] == "media.previous"


def test_uncontradicted_hint_is_not_overruled_by_the_model():
    """The mirror image, and the regression this rule exists to
    prevent: when the hint is its own family's best lexical match
    the model must NOT be consulted, so a wrong model answer
    cannot replace a correct deterministic one."""
    eng = engine()

    calls = []

    def _never_called(text):
        calls.append(text)
        return _semantic_intent("document.create_txt")

    eng._detect_os_intent = lambda text: _det_intent(
        "gui.type_text", parameters={"requires_target": True}
    )
    eng._resolve_with_capability_control_plane = (
        lambda decision: decision
    )
    eng._try_semantic_intent_resolution = _never_called

    decision = eng.decide("write hello world")

    assert calls == []
    assert decision["intent"] == "gui.type_text"


def test_hint_is_kept_when_the_semantic_layer_declines():
    """The semantic layer answering null must not lose a decision
    the deterministic layer already made."""
    eng = engine()

    eng._detect_os_intent = lambda text: _det_intent(
        "media.play_pause",
        parameters={"requires_target": True},
    )
    eng._resolve_with_capability_control_plane = (
        lambda decision: decision
    )
    eng._try_semantic_intent_resolution = lambda text: None

    decision = eng.decide("synthetic unanchored family probe")

    assert decision["level"] == 3
    assert decision["intent"] == "media.play_pause"


def test_anchored_deterministic_answer_is_not_sent_to_the_model():
    """The fast path must survive the fix: an anchored match is
    answered without paying for a model call."""
    eng = engine()

    eng._detect_os_intent = lambda text: _det_intent(
        "file.delete", target="report.pdf"
    )
    eng._resolve_with_capability_control_plane = (
        lambda decision: decision
    )

    calls = []

    def _never_called(text):
        calls.append(text)
        return _semantic_intent("file.delete")

    eng._try_semantic_intent_resolution = _never_called

    decision = eng.decide("delete report.pdf")

    assert calls == []
    assert decision["intent"] == "file.delete"