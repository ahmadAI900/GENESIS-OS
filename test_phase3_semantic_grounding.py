"""
Phase 3 — semantic grounding foundation.

Root cause these tests pin
-------------------------
`looks_actionable` was a BOOLEAN over lexical probes. A boolean has
no third value, so "I cannot classify this" collapses into the same
False as "this is conversation". Proved on synthetic input: a real
indirect command and ordinary conversation produce identical probe
signals (domain evidence, specific action verb, state hint, small
talk — all False for all of them), and a knowledge question does too.
No boolean function of those probes can separate them. That is why
global "ask the model" breaks the false-positive guards, and why a
bigger verb list just moves the boundary.

The fix is a third tier plus checkable evidence. `lexical_actionability`
returns BLOCKED / ACTIONABLE / AMBIGUOUS on the SAME existing probes,
and only AMBIGUOUS escalates to `GroundingResult`, which requires:

  * a quoted span that is VERBATIM in the request (fidelity),
  * a span carrying at least one content word (substance),
  * a registered capability,
  * policy/safety permitting the route,
  * the existing CapabilityResolver independently agreeing.

Grounding consumes evidence the system already produces
(CapabilityResolutionEvidence, ExecutionSafety, CapabilityResolver,
SELECTION_BOUNDARIES, capability descriptors) rather than introducing a
new contract. Cross-domain arbitration is deliberately NOT implemented;
GroundingResult only carries the fields a later stage would need.

ALL requests here are SYNTHETIC and share no wording with the Phase 3
measurement corpora. Two tests enforce that mechanically against the
sealed corpora.

No model is contacted: the grounding probe is stubbed per test, so
these assert the contract rather than any particular model's answers.
"""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

BACKEND = Path(__file__).resolve().parent


# =========================================================
# HELPERS
# =========================================================

def _resolver(probe_result):
    """An LLMIntentResolver whose grounding probe is stubbed."""
    resolver = LLMIntentResolver(ai_engine=None)
    calls = []

    def _stub(text, deadline):
        calls.append(text)
        if callable(probe_result):
            return probe_result(text)
        return probe_result

    resolver._grounding_probe = _stub
    resolver.probe_calls = calls
    return resolver


def _accepted(capability_id, anchor):
    return {
        "actionable": True,
        "capability_id": capability_id,
        "anchor": anchor,
    }


def _declined():
    return {"actionable": False, "capability_id": None,
            "anchor": None}


def _det_intent(intent, **extra):
    decision = {
        "level": 3,
        "mode": "os",
        "task": "synthetic probe",
        "agent": None,
        "agents": [],
        "intent": intent,
        "application": None,
        "target": None,
        "parameters": {"requires_target": True},
        "confidence": 0.95,
        "reason": "synthetic",
    }
    decision.update(extra)
    return decision


def _engine_with_grounding(grounded, deterministic=None):
    engine = WorkflowDecisionEngine()
    engine._llm_resolver = _resolver(grounded)
    engine._detect_os_intent = lambda text: deterministic
    engine._detect_extended_os_intent = lambda text: None
    return engine


# =========================================================
# 1. LEXICAL TIER — the same probes, asked whether they are sure
# =========================================================

def test_tier_is_three_valued():
    assert (
        LLMIntentResolver.lexical_actionability(
            "i need this written out somewhere durable"
        ) == LLMIntentResolver.AMBIGUOUS
    )
    assert (
        LLMIntentResolver.lexical_actionability(
            "that genuinely cheered me up"
        ) == LLMIntentResolver.AMBIGUOUS
    )
    assert (
        LLMIntentResolver.lexical_actionability("open notepad")
        == LLMIntentResolver.ACTIONABLE
    )
    for text in (
        "hello there friend",
        "she set the table before we arrived",
    ):
        assert (
            LLMIntentResolver.lexical_actionability(text)
            == LLMIntentResolver.BLOCKED
        ), text


def test_boolean_gate_keeps_its_cost_gate_contract():
    """The boolean still reports only the ACTIONABLE tier, so every
    pinned caller and test is unaffected."""
    assert LLMIntentResolver.looks_actionable("open notepad") is True
    for text in (
        "that genuinely cheered me up",
        "i need this written out somewhere durable",
        "hello there friend",
    ):
        assert LLMIntentResolver.looks_actionable(text) is False, text


# =========================================================
# 2. TEST 1 — ambiguous but actionable -> LLM path permitted
# =========================================================

def test_ambiguous_actionable_request_permits_the_llm_path():
    request = "i need this written out somewhere durable"
    assert (
        LLMIntentResolver.lexical_actionability(request)
        == LLMIntentResolver.AMBIGUOUS
    )
    resolver = _resolver(
        _accepted("document.create_txt", "written out somewhere durable")
    )
    result = resolver.grounded_capability(request)
    assert result is not None
    assert result.capability_id == "document.create_txt"
    assert resolver.probe_calls, "the probe must actually have run"


# =========================================================
# 3. TEST 2 — ambiguous conversation -> non-actionable
# =========================================================

def test_ambiguous_conversation_remains_non_actionable():
    resolver = _resolver(_declined())
    for text in (
        "you make me happy",
        "that genuinely cheered me up",
        "we should catch up sometime",
    ):
        assert LLMIntentResolver.lexical_actionability(
            text
        ) == LLMIntentResolver.AMBIGUOUS, text
        assert resolver.grounded_capability(text) is None, text


# =========================================================
# 4. TEST 3 — knowledge question with an action-like verb
# =========================================================

def test_knowledge_question_with_action_verb_stays_non_actionable():
    """'go', 'way' and 'start' all occur in the action-verb list, yet
    these are advice questions, not computer requests. The tier is
    AMBIGUOUS, so this exercises the grounding path rather than a
    lexical block."""
    knowledge = (
        "how do i go about learning python quickly",
        "what is the best way to memorise vocabulary",
        "how would you recommend i start learning guitar",
    )
    for text in knowledge:
        assert LLMIntentResolver.lexical_actionability(
            text
        ) == LLMIntentResolver.AMBIGUOUS, text
        resolver = _resolver(_declined())
        assert resolver.grounded_capability(text) is None, text


def test_knowledge_question_cannot_be_forced_through_by_grounding():
    """Even when a model claims actionable, an unfaithful or
    contentless justification leaves the request non-actionable."""
    text = "how do i go about learning python quickly"
    resolver = _resolver(
        _accepted("web.research", "learning python quickly")
    )
    # A faithful, substantive anchor is possible here, so this case
    # is decided by the model declining rather than by the contract.
    # The contract is what must hold: with no evidence, nothing acts.
    strict = LLMIntentResolver.evaluate_grounding(
        text, "web.research", ""
    )
    assert strict.grounded is False
    assert strict.reasons


# =========================================================
# 5. TEST 4 — actionable request phrased as a question
# =========================================================

def test_question_form_actionable_request_permits_the_llm_path():
    request = "would you mind pulling up my diary for today"
    assert (
        LLMIntentResolver.lexical_actionability(request)
        == LLMIntentResolver.AMBIGUOUS
    )
    assert request.strip().endswith("today")

    resolver = _resolver(
        _accepted("file.open", "pulling up my diary")
    )
    result = resolver.grounded_capability(request)
    assert result is not None
    assert result.capability_id == "file.open"


# =========================================================
# 6. TEST 5 / 6 — deterministic authority
# =========================================================

def test_strong_deterministic_anchor_remains_authoritative():
    """A well-grounded semantic alternative must NOT overturn a
    deterministic match that names a concrete target."""
    engine = _engine_with_grounding(
        _accepted("document.delete", "report.pdf"),
        deterministic=_det_intent(
            "file.delete", target="report.pdf"
        ),
    )
    decision = engine.decide("delete report.pdf")
    assert decision["intent"] == "file.delete"


def test_weak_semantic_candidate_does_not_override_deterministic():
    """A weak semantic result is not grounds for overriding
    deterministic evidence."""
    engine = _engine_with_grounding(
        _accepted("document.delete", "some other unrelated place"),
        deterministic=_det_intent(
            "file.delete", target="report.pdf"
        ),
    )
    decision = engine.decide("delete report.pdf")
    assert decision["intent"] == "file.delete"


def test_no_model_call_when_deterministic_evidence_is_authoritative():
    engine = WorkflowDecisionEngine()
    engine._detect_os_intent = lambda text: _det_intent(
        "file.delete", target="report.pdf"
    )
    engine._resolve_with_capability_control_plane = (
        lambda decision: decision
    )
    calls = []
    engine._try_semantic_intent_resolution = (
        lambda text: calls.append(text)
    )
    decision = engine.decide("delete report.pdf")
    assert calls == []
    assert decision["intent"] == "file.delete"


# =========================================================
# 7. TEST 7 — valid capability, insufficient grounding
# =========================================================

@pytest.mark.parametrize(
    "anchor,why",
    [
        ("save it under a different heading", "not in the request"),
        ("the one for me please", "no content word"),
        ("", "no span at all"),
    ],
)
def test_valid_capability_with_insufficient_grounding_is_rejected(
    anchor, why
):
    result = LLMIntentResolver.evaluate_grounding(
        "i need this written out somewhere durable",
        "document.create_txt",
        anchor,
    )
    assert result.grounded is False, why
    assert result.reasons, why


# =========================================================
# 8. TEST 8 — invalid model capability id
# =========================================================

def test_invalid_capability_id_is_rejected():
    result = LLMIntentResolver.evaluate_grounding(
        "i need this written out somewhere durable",
        "no.such.registered.capability",
        "written out somewhere durable",
    )
    assert result.grounded is False
    assert result.reasons

    resolver = _resolver(
        _accepted("no.such.registered.capability",
                  "written out somewhere durable")
    )
    assert resolver.grounded_capability(
        "i need this written out somewhere durable"
    ) is None


# =========================================================
# 9. TEST 9 — safety / authorization is never bypassed
# =========================================================

def test_policy_denial_rejects_the_candidate(monkeypatch):
    import genesis_os.execution_safety as safety_module

    monkeypatch.setattr(
        safety_module.ExecutionSafety,
        "check",
        staticmethod(
            lambda operation: SimpleNamespace(
                allowed=False, requires_confirmation=False,
                reason="policy denies this in tests",
            )
        ),
    )
    resolver = _resolver(
        _accepted("application.open", "pulling up my diary")
    )
    assert resolver.grounded_capability(
        "would you mind pulling up my diary for today"
    ) is None


def test_approval_gated_candidate_is_handed_to_the_policy_flow():
    """A capability that needs confirmation is still grounded, but
    the confirmation requirement is carried so the existing approval
    flow runs. Grounding must not silently launder a gated
    capability into an ordinary one.

    The anchor is a proper span: grounding must leave at least one
    content word of the request outside it, otherwise the quote is
    trivially verbatim for every capability."""
    result = LLMIntentResolver.evaluate_grounding(
        "get rid of that draft from my downloads", "file.delete",
        "get rid of that draft",
    )
    assert result.grounded is True
    assert result.requires_confirmation is True
    assert result.risk_level == "critical"
    assert result.policy_allowed is True


# =========================================================
# 10. TEST 10 — same-family 1a behaviour intact
# =========================================================

def test_same_family_override_behaviour_is_intact():
    engine = WorkflowDecisionEngine()

    # Contradicted family: a sibling describes the request better.
    assert engine._deterministic_match_is_only_a_hint(
        _det_intent("media.play_pause",
                    parameters={}),
        "go back to the previous track",
    )
    # Uncontradicted family: the hint stands.
    assert not engine._deterministic_match_is_only_a_hint(
        _det_intent("gui.type_text", parameters={}),
        "write hello world",
    )
    # Anchored matches never escalate.
    assert not engine._deterministic_match_is_only_a_hint(
        _det_intent("file.delete", target="report.pdf"), "x y"
    )


def test_contradicted_family_hint_is_overruled_end_to_end():
    engine = WorkflowDecisionEngine()
    engine._detect_os_intent = lambda text: _det_intent(
        "media.play_pause", parameters={}
    )
    engine._resolve_with_capability_control_plane = (
        lambda decision: decision
    )
    engine._try_semantic_intent_resolution = lambda text: {
        "level": 3, "mode": "os", "task": text, "agent": None,
        "agents": [], "intent": "media.previous",
        "application": None, "target": None,
        "parameters": {
            "_semantic_resolution": True,
            "_capability_resolution": {
                "status": "resolved",
                "capability_id": "media.previous",
            },
        },
        "confidence": 0.85, "reason": "synthetic",
    }
    decision = engine.decide("go back to the previous track")
    assert decision["intent"] == "media.previous"


# =========================================================
# 11. TEST 11 — Phase 0 forensic regression
# =========================================================

def test_phase0_write_hello_world_remains_protected():
    """The pinned Phase 0 guard. "write hello world" is correctly
    gui.type_text from the deterministic layer; no gui sibling
    describes it better, so the model is never consulted and cannot
    turn it into a document capability."""
    engine = WorkflowDecisionEngine()

    # Mirrors the real decision shape: a targetless gui.type_text
    # with an explicit target requirement, which is what promotes it.
    hint = _det_intent(
        "gui.type_text", parameters={"requires_target": True}
    )

    assert not engine._deterministic_match_is_only_a_hint(
        hint, "write hello world"
    )

    # And the full path keeps the deterministic answer.
    engine._detect_os_intent = lambda text: hint
    engine._resolve_with_capability_control_plane = (
        lambda decision: decision
    )
    calls = []
    engine._try_semantic_intent_resolution = (
        lambda text: calls.append(text)
    )
    decision = engine.decide("write hello world")
    assert calls == []
    assert decision["intent"] == "gui.type_text"


# =========================================================
# 12. TEST 12 — no measurement corpus phrase, implementation OR tests
# =========================================================

def test_no_measurement_corpus_phrase_anywhere():
    """Enforced mechanically against both sealed corpora, so it fails
    the moment a benchmark phrase is pasted into production code or
    into this file."""
    sources = [
        BACKEND / "genesis_os" / "llm_intent_resolver.py",
        BACKEND / "genesis_os" / "capability_resolution.py",
        BACKEND / "agents" / "workflow_decision.py",
        BACKEND / "test_phase3_semantic_grounding.py",
    ]
    raw = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in sources
    )

    def norm(text):
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    # (a) whole-phrase contiguity, newlines collapsed so a paste
    #     spanning several docstring lines is still caught.
    collapsed = norm(raw)

    # (b) per-line four-word runs. Per line, because a 4-gram over the
    #     whole file straddles line boundaries and reports nonsense.
    per_line_4grams = set()
    for line in raw.splitlines():
        words = norm(line).split()
        for index in range(len(words) - 3):
            per_line_4grams.add(tuple(words[index:index + 4]))

    stop = LLMIntentResolver._GROUNDING_STOPWORDS
    checked = 0
    for sealed_name in (
        "phase3_v3_SEALED.json", "phase3_v4_SEALED.json"
    ):
        sealed_file = BACKEND / sealed_name
        if not sealed_file.exists():
            continue
        sealed = json.loads(
            sealed_file.read_text(encoding="utf-8")
        )
        for split in ("dev3", "final3", "dev4", "final4"):
            for item in sealed.get(split, []):
                phrase = item.get("phrase")
                if not phrase:
                    continue
                checked += 1
                normalised = norm(phrase)
                assert normalised not in collapsed, (
                    f"benchmark phrase reused verbatim: {phrase!r}"
                )
                words = normalised.split()
                for start in range(len(words) - 3):
                    run = tuple(words[start:start + 4])
                    if len([w for w in run if w not in stop]) < 2:
                        continue
                    assert run not in per_line_4grams, (
                        f"four-word run from a benchmark phrase appears "
                        f"in the code: {' '.join(run)!r} from {phrase!r}"
                    )

    assert checked > 0, "no corpus items were inspected"


# =========================================================
# 13. TEST 13 — no sentence-specific exception
# =========================================================

# Functions that decide actionability and grounding. This is the
# surface a sentence-specific exception would have to live in.
GROUNDING_FUNCTIONS = {
    "llm_intent_resolver": (
        "lexical_actionability",
        "evaluate_grounding",
        "grounded_capability",
        "_grounding_probe",
    ),
    "workflow_decision": (
        "_grounded_os_decision",
        "_deterministic_match_is_only_a_hint",
    ),
}

# Names holding the incoming request text.
REQUEST_NAMES = ("text", "request", "anchor", "lowered", "phrase",
                 "original_text")


def _functions_by_name(tree):
    found = {}
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            found[node.name] = node
    return found


def test_no_request_is_compared_against_a_hardcoded_phrase():
    """A sentence-specific exception has a recognisable shape: the
    incoming request compared against a literal phrase, e.g.
    `if "please open the drawing tool" in text` or
    `text == "shut that down"`.

    Asserting that shape is exact. An earlier heuristic that simply
    counted words in literals false-positived on ordinary prose like
    a reason string, which is how it would have been tuned away
    instead of tightened.

    Existing regex probes are deliberately NOT flagged: keywords and
    regex as fast hints are an explicit roadmap requirement.
    """
    checked = 0

    for module_name, function_names in GROUNDING_FUNCTIONS.items():
        relative = (
            "genesis_os/llm_intent_resolver.py"
            if module_name == "llm_intent_resolver"
            else "agents/workflow_decision.py"
        )
        tree = ast.parse(
            (BACKEND / relative).read_text(encoding="utf-8")
        )
        functions = _functions_by_name(tree)

        for name in function_names:
            assert name in functions, (
                f"{name} missing from {relative}"
            )
            function = functions[name]
            checked += 1

            for node in ast.walk(function):
                if not isinstance(node, ast.Compare):
                    continue
                operands = [node.left, *node.comparators]
                for operand in operands:
                    if not isinstance(operand, ast.Constant):
                        continue
                    if not isinstance(operand.value, str):
                        continue
                    # A request-shaped literal compared directly
                    # against a request variable.
                    for other in operands:
                        if other is operand:
                            continue
                        identifier = getattr(other, "id", None)
                        if identifier in REQUEST_NAMES:
                            raise AssertionError(
                                f"{relative}:{function.name} compares "
                                f"the request against a literal "
                                f"phrase {operand.value!r} — that is a "
                                f"sentence-specific rule"
                            )

    assert checked == 6


def test_no_phrase_table_exists_in_the_grounding_code():
    """A phrase dictionary is the failure mode the roadmap forbids.

    Scoped to the grounding/actionability functions rather than whole
    modules: workflow_decision.py legitimately contains pre-existing
    regex and word lists that are part of the 'keywords as fast hints'
    requirement. What must not exist is a request-phrase table inside
    the code that decides grounding.
    """
    stop = LLMIntentResolver._GROUNDING_STOPWORDS
    violations = []

    for module_name, function_names in GROUNDING_FUNCTIONS.items():
        relative = (
            "genesis_os/llm_intent_resolver.py"
            if module_name == "llm_intent_resolver"
            else "agents/workflow_decision.py"
        )
        tree = ast.parse(
            (BACKEND / relative).read_text(encoding="utf-8")
        )
        functions = _functions_by_name(tree)

        for name in function_names:
            function = functions[name]
            for node in ast.walk(function):
                if not isinstance(
                    node, (ast.List, ast.Tuple, ast.Set, ast.Dict)
                ):
                    continue
                phrases = [
                    element.value
                    for element in ast.walk(node)
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                    and " " in element.value
                    and len([
                        word
                        for word in re.findall(
                            r"[A-Za-z]+", element.value
                        )
                        if word.lower() not in stop
                    ]) >= 2
                ]
                if len(phrases) >= 3:
                    violations.append(
                        f"{relative}:{function.name} holds "
                        f"{len(phrases)} request-shaped literals"
                    )

    assert not violations, violations


# =========================================================
# 14. GROUNDING RESULT — reusable, and not arbitration
# =========================================================

def test_grounding_result_carries_reusable_descriptor_facts():
    """A later stage (cross-domain arbitration) needs these fields,
    so their presence is pinned now even though arbitration itself is
    not implemented."""
    result = LLMIntentResolver.evaluate_grounding(
        "i need this written out somewhere durable",
        "document.create_txt",
        "written out somewhere durable",
    )
    payload = result.to_dict()

    for field in (
        "domain", "category", "operation", "declared_inputs",
        "risk_level", "requires_confirmation", "policy_allowed",
        "status", "confidence", "alternatives", "strength",
        "evidence", "reasons",
    ):
        assert field in payload, field

    assert payload["domain"] == "document"
    assert payload["operation"] == "document.create_txt"
    assert "path" in payload["declared_inputs"]

    # Evidence reuses the existing typed contract rather than
    # inventing one.
    match_types = [item["match_type"] for item in payload["evidence"]]
    assert "semantic_grounding_anchor" in match_types
    assert "exact_capability_id" in match_types


def test_grounding_result_is_immutable():
    import dataclasses

    result = LLMIntentResolver.evaluate_grounding(
        "i need this written out somewhere durable",
        "document.create_txt", "written out somewhere durable",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.grounded = False


def test_strength_is_zero_without_a_faithful_substantive_anchor():
    """Fidelity and substance are hard gates, so they cannot be
    offset by high resolver confidence."""
    faithful = LLMIntentResolver.evaluate_grounding(
        "i need this written out somewhere durable",
        "document.create_txt", "written out somewhere durable",
    )
    unfaithful = LLMIntentResolver.evaluate_grounding(
        "i need this written out somewhere durable",
        "document.create_txt", "somewhere else entirely",
    )
    assert faithful.strength > 0
    assert unfaithful.strength == 0.0
    assert faithful.confidence == unfaithful.confidence


def test_grounded_decision_is_promoted_through_the_control_plane():
    engine = _engine_with_grounding(
        _accepted("document.create_txt", "written out somewhere durable")
    )
    decision = engine.decide("i need this written out somewhere durable")

    assert decision["level"] == 3
    assert decision["intent"] == "document.create_txt"

    resolution = decision["parameters"]["_capability_resolution"]
    assert resolution["status"] == "resolved"
    assert resolution["capability_id"] == "document.create_txt"

    grounding = decision["parameters"]["_semantic_grounding"]
    assert grounding["grounded"] is True
    assert grounding["lexical_tier"] == "ambiguous"
    assert grounding["domain"] == "document"


def test_conversation_never_becomes_a_level3_action_end_to_end():
    """Stronger than a gate-only assertion: whatever the model
    returns, an ordinary conversational request must not produce a
    Level 3 action."""
    for text in (
        "you make me happy",
        "that genuinely cheered me up",
        "how do i go about learning python quickly",
        "can you do something for me",
    ):
        engine = _engine_with_grounding(_declined())
        decision = engine.decide(text)
        assert decision["level"] != 3, text
        assert not decision.get("intent"), text


def test_blocked_text_is_never_escalated():
    resolver = _resolver(
        _accepted("application.open", "hello there friend")
    )
    assert resolver.grounded_capability("hello there friend") is None
    assert resolver.probe_calls == []


def test_actionable_text_pays_nothing_for_the_probe():
    resolver = _resolver(
        _accepted("application.open", "open notepad")
    )
    assert resolver.grounded_capability("open notepad") is None
    assert resolver.probe_calls == []