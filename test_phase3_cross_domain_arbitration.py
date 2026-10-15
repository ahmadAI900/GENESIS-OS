"""
Phase 3 — cross-domain capability arbitration.

ROOT CAUSE THIS PINS
--------------------
`decide()` returned the deterministic candidate at the promotion gate
before the semantic layer could be consulted, and the only hook able
to raise a challenge compared siblings INSIDE the matched capability's
own domain. A cross-domain mistake was therefore invisible by
construction: with det=file.move and the correct answer in the folder
domain, no family test could ever fire.

Arbitration is capability-first. Both candidates are named registered
capabilities, so no domain is privileged and the comparison cannot be
family-scoped. Every inconclusive or unproven path resolves to
DETERMINISTIC: a wrong semantic answer replaces a working route, so
the burden of proof sits with the challenger.

THREE LOCAL SIGNALS WERE TESTED AND REJECTED before this design, and
none is used: top per-domain vocabulary evidence (domain vocabularies
differ in size by more than 15x, so one incidental hit in a small
domain outranked every genuine hit in a large one), operation-token
sharing (caught some classes, missed others), and description affinity
(tied on nearly every real request).

Only the model PROBES are stubbed here. arbitrate_capabilities() and
evaluate_grounding() are the real implementations, so these tests
exercise the actual admissibility and selection policy.

Deterministic candidates are built with their capability's own
declared required inputs (see `_det_intent`), because an exact-ID hit
with unmet preconditions resolves UNAVAILABLE and `decide()` would
then return before arbitration is reached. That is fixture hygiene;
no precondition logic is asserted here. The asymmetric case -- a
SEMANTIC candidate, which never carries inputs -- is asserted
explicitly in
`test_precondition_bearing_semantic_candidate_can_be_selected_but_never_installed`.

All requests are SYNTHETIC paraphrases. The final tests enforce,
mechanically, that no sealed Phase 3 corpus phrase appears in this
file or in the production modules it exercises.
"""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.llm_intent_resolver import LLMIntentResolver

BACKEND = Path(__file__).resolve().parent

# A request whose wording names a different capability domain than
# the deterministic candidate. Used to make the trigger fire.
CROSS_DOMAIN_REQUEST = "relocate that whole drawer into my archive area"
CROSS_DOMAIN_DET = "file.move"
CROSS_DOMAIN_SEM = "folder.move"
CROSS_DOMAIN_ANCHOR = "relocate that whole drawer"


def _det_intent(intent, confidence=0.95, **extra):
    """A synthetic deterministic candidate.

    The candidate carries the capability's OWN declared required
    inputs. This is fixture hygiene, not a test of the control plane:
    17 capabilities declare preconditions, every one of which is a
    required input name, and an exact-ID hit whose preconditions are
    unmet resolves UNAVAILABLE rather than RESOLVED. A candidate that
    omits them therefore never survives
    `_resolve_with_capability_control_plane`, `decide()` gets None,
    and arbitration is never reached -- so the test would silently
    measure nothing. The lookup is registry-derived and generic; no
    capability id is named here.
    """
    from genesis_os.capability_registry import CapabilityRegistry

    parameters = {"requires_target": True}
    descriptor = (
        CapabilityRegistry.get(intent)
        if isinstance(intent, str) and "." in intent else None
    )
    if descriptor is not None:
        for name in descriptor.preconditions:
            parameters[name] = f"synthetic {name}"
    decision = {
        "level": 3, "mode": "os", "task": "synthetic", "agent": None,
        "agents": [], "intent": intent, "application": None,
        "target": None,
        "parameters": parameters,
        "confidence": confidence, "reason": "synthetic",
    }
    decision.update(extra)
    return decision


def _grounded(request, capability_id, anchor):
    """A REAL GroundingResult from the production evaluator."""
    return LLMIntentResolver.evaluate_grounding(
        request, capability_id, anchor
    )


def _resolver(grounding=None, choice=None, anchor=""):
    resolver = LLMIntentResolver(ai_engine=None)
    resolver._grounding = grounding
    resolver.grounded_calls = []
    resolver.arbitration_calls = []

    def _grounded_capability(text, **kwargs):
        resolver.grounded_calls.append(text)
        return resolver._grounding

    def _probe(text, deterministic_capability, semantic_capability,
               deadline):
        resolver.arbitration_calls.append(
            (deterministic_capability, semantic_capability)
        )
        if callable(choice):
            return choice(text)
        return {"choice": choice, "anchor": anchor}

    resolver.grounded_capability = _grounded_capability
    resolver.arbitration_probe = _probe
    return resolver


def _engine(grounding=None, choice=None, anchor="", deterministic=None):
    engine = WorkflowDecisionEngine()
    engine._llm_resolver = _resolver(grounding, choice, anchor)
    engine._detect_os_intent = lambda text: deterministic
    engine._detect_extended_os_intent = lambda text: None
    return engine


def _cross_domain_engine(choice, anchor=CROSS_DOMAIN_ANCHOR,
                         semantic=CROSS_DOMAIN_SEM):
    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, semantic, anchor
    )
    return _engine(
        grounding=grounding,
        choice=choice,
        anchor=anchor,
        deterministic=_det_intent(CROSS_DOMAIN_DET),
    )


# =========================================================
# 1-2. CANDIDATES AGREE / DETERMINISTIC RETAINED
# =========================================================

def test_candidates_agree_no_arbitration_needed():
    request = "shift that entire drawer across into my archive area"
    grounding = _grounded(request, "folder.organize",
                          "shift that entire drawer")
    engine = _engine(
        grounding=grounding,
        deterministic=_det_intent("folder.organize"),
    )
    decision = engine.decide(request)
    assert decision["intent"] == "folder.organize"
    assert engine._llm_resolver.arbitration_calls == []


def test_deterministic_retained_when_comparison_prefers_it():
    engine = _cross_domain_engine("A")
    decision = engine.decide(CROSS_DOMAIN_REQUEST)
    assert decision["intent"] == CROSS_DOMAIN_DET
    arbitration = decision["parameters"]["_capability_arbitration"]
    assert arbitration["selected"] == "deterministic"
    assert arbitration["deterministic_capability"] == CROSS_DOMAIN_DET


def test_no_challenger_means_no_model_call():
    """The fast path: a clear match on unambiguous wording pays
    nothing and records no arbitration."""
    engine = _engine(grounding=None,
                     deterministic=_det_intent("volume.up"))
    decision = engine.decide("nudge the volume up a notch")
    assert decision["intent"] == "volume.up"
    assert engine._llm_resolver.grounded_calls == []
    assert "_capability_arbitration" not in decision["parameters"]


# =========================================================
# 3-6. CHALLENGER MUST EARN ITS PLACE
# =========================================================

def test_invalid_semantic_capability_cannot_challenge():
    result = _grounded(
        CROSS_DOMAIN_REQUEST, "no.such.capability.at.all",
        CROSS_DOMAIN_ANCHOR,
    )
    assert result.grounded is False
    assert result.reasons


def test_unregistered_semantic_candidate_is_not_admissible():
    engine = _cross_domain_engine("B", semantic="no.such.capability")
    decision = engine.decide(CROSS_DOMAIN_REQUEST)
    assert decision["intent"] == CROSS_DOMAIN_DET


def test_missing_grounding_is_rejected():
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B", "anchor": CROSS_DOMAIN_ANCHOR,
    }
    arbitration = resolver.arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), None
    )
    assert arbitration.selected == "deterministic"
    assert "grounded" in arbitration.reason


def test_ungrounded_semantic_candidate_is_not_admissible():
    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_SEM, "a span nobody typed"
    )
    assert grounding.grounded is False
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B", "anchor": CROSS_DOMAIN_ANCHOR,
    }
    arbitration = resolver.arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), grounding
    )
    assert arbitration.selected == "deterministic"
    assert "grounded" in arbitration.reason


def test_policy_denied_semantic_candidate_is_rejected(monkeypatch):
    """Policy is re-checked at arbitration time and never inherited
    from an earlier verdict.

    The grounding is built BEFORE the denial is applied, so this
    isolates the arbitration-time check rather than the grounding
    contract's own policy gate.
    """
    import genesis_os.execution_safety as safety_module

    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_SEM, CROSS_DOMAIN_ANCHOR
    )
    assert grounding.grounded is True
    assert grounding.policy_allowed is True

    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B", "anchor": CROSS_DOMAIN_ANCHOR,
    }
    monkeypatch.setattr(
        safety_module.ExecutionSafety, "check",
        staticmethod(lambda operation: SimpleNamespace(
            allowed=False, requires_confirmation=False,
            reason="denied in test",
        )),
    )
    arbitration = resolver.arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), grounding
    )
    assert arbitration.selected == "deterministic"
    assert "policy" in arbitration.reason


# =========================================================
# 7-9. EVIDENCE AND LEGITIMATE CHALLENGE
# =========================================================

def test_cross_domain_challenge_is_admitted_and_can_win():
    """The class that motivated this layer.

    TWO FACTS, TWO PLACES. The old single assertion conflated them,
    so it is now split.

    ARBITRATION runs first and does select the cross-domain semantic
    candidate: that is the policy this file tests, and it is
    unchanged. PROMOTION runs second, through the same control plane
    as every other semantic decision, and refuses the candidate
    because `folder.move` declares `destination` and a semantic
    decision carries no inputs at all -- `_arbitrate_os_decision`
    and `_grounded_os_decision` both build `parameters` from two
    metadata keys. The caller therefore receives the deterministic
    candidate.

    Nothing about arbitration was changed to get here. This is the
    same refusal the `file.rename` tests pin, seen from the
    arbitration side, and it is logged as a named future item in the
    Phase 3 closeout rather than worked around.
    """
    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_SEM, CROSS_DOMAIN_ANCHOR
    )
    verdict = _resolver(
        grounding=grounding, choice="B", anchor=CROSS_DOMAIN_ANCHOR
    ).arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), grounding
    )
    assert verdict.selected == "semantic"
    assert verdict.deterministic_capability == CROSS_DOMAIN_DET
    assert verdict.semantic_capability == CROSS_DOMAIN_SEM
    assert verdict.anchor_faithful is True

    engine = _cross_domain_engine("B")
    decision = engine.decide(CROSS_DOMAIN_REQUEST)
    assert engine._llm_resolver.arbitration_calls == [
        (CROSS_DOMAIN_DET, CROSS_DOMAIN_SEM)
    ]
    assert decision["intent"] == CROSS_DOMAIN_DET


def test_contradiction_trigger_is_generic_not_domain_specific():
    """Registry-derived domain vocabulary. Fires for a folder/file
    disagreement with no rule naming either, and stays quiet when the
    request speaks the matched domain's own language."""
    assert LLMIntentResolver.cross_domain_contradiction(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_DET
    )
    assert not LLMIntentResolver.cross_domain_contradiction(
        "move that file into the archive area", "file.move"
    )
    assert not LLMIntentResolver.cross_domain_contradiction(
        "open notepad", "application.open"
    )


def test_same_domain_sibling_challenge_still_works():
    """Arbitration does not replace the existing same-family hook."""
    engine = WorkflowDecisionEngine()
    assert engine._deterministic_match_is_only_a_hint(
        _det_intent("media.play_pause", parameters={}),
        "go back to the previous track",
    )


# =========================================================
# 10-11. UNRELATED CHALLENGERS MUST NOT WIN
# =========================================================

def test_unrelated_semantic_candidate_does_not_override():
    """A valid capability that is plainly about something else."""
    engine = _cross_domain_engine("A", semantic="volume.up")
    decision = engine.decide(CROSS_DOMAIN_REQUEST)
    assert decision["intent"] == CROSS_DOMAIN_DET


def test_unfaithful_anchor_keeps_deterministic():
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B",
        "anchor": "a phrase the user never typed",
    }
    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_SEM, CROSS_DOMAIN_ANCHOR
    )
    arbitration = resolver.arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), grounding
    )
    assert arbitration.selected == "deterministic"
    assert arbitration.anchor_faithful is False
    assert "verbatim" in arbitration.reason


def test_abstention_keeps_deterministic():
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": None, "anchor": "",
    }
    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_SEM, CROSS_DOMAIN_ANCHOR
    )
    arbitration = resolver.arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), grounding
    )
    assert arbitration.selected == "deterministic"


def test_no_verdict_keeps_deterministic():
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: None
    grounding = _grounded(
        CROSS_DOMAIN_REQUEST, CROSS_DOMAIN_SEM, CROSS_DOMAIN_ANCHOR
    )
    arbitration = resolver.arbitrate_capabilities(
        CROSS_DOMAIN_REQUEST, _det_intent(CROSS_DOMAIN_DET), grounding
    )
    assert arbitration.selected == "deterministic"


# =========================================================
# 12-14. NON-ACTIONABLE TEXT AND QUESTIONS
# =========================================================

def test_ordinary_conversation_remains_non_actionable():
    for text in ("you make me happy",
                 "that genuinely cheered me up",
                 "we should catch up sometime"):
        engine = _engine(grounding=None)
        decision = engine.decide(text)
        assert decision["level"] != 3, text
        assert not decision.get("intent"), text
        # A probe is permitted here (lexically ambiguous wording); what
        # must never happen is a capability being adopted.
        assert "_capability_arbitration" not in (
            decision.get("parameters") or {}
        )


def test_knowledge_with_action_verb_remains_non_actionable():
    """These carry action-list verbs and are still not requests."""
    for text in ("how do i go about learning python quickly",
                 "what is the best way to memorise vocabulary",
                 "how would you recommend i start learning guitar"):
        assert LLMIntentResolver.lexical_actionability(text) == (
            LLMIntentResolver.AMBIGUOUS
        ), text
        engine = _engine(grounding=None)
        decision = engine.decide(text)
        assert decision["level"] != 3, text
        assert not decision.get("intent"), text
        assert "_capability_arbitration" not in (
            decision.get("parameters") or {}
        )


def test_actionable_question_remains_actionable():
    request = "would you mind pulling up my diary for today"
    grounding = _grounded(request, "file.open", "pulling up my diary")
    engine = _engine(grounding=grounding, deterministic=None)
    decision = engine.decide(request)
    assert decision["level"] == 3
    assert decision["intent"] == "file.open"


# =========================================================
# 15. PHASE 0 GUARD
# =========================================================

def test_phase0_write_hello_world_is_gui_type_text():
    """The pinned behaviour must survive arbitration."""
    engine = WorkflowDecisionEngine()
    hint = _det_intent(
        "gui.type_text", parameters={"requires_target": True}
    )
    assert not engine._deterministic_match_is_only_a_hint(
        hint, "write hello world"
    )

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


def test_arbitration_cannot_redirect_the_phase0_guard():
    """If arbitration does fire for this wording and the challenger is
    a document capability, the deterministic answer must still be
    reachable and is what is chosen."""
    engine = WorkflowDecisionEngine()
    hint = _det_intent(
        "gui.type_text", parameters={"requires_target": True}
    )
    engine._detect_os_intent = lambda text: hint
    engine._llm_resolver = _resolver(
        grounding=_grounded(
            "write hello world", "document.create_txt",
            "write hello world",
        ),
        choice="A",
        anchor="write hello world",
    )
    decision = engine.decide("write hello world")
    assert decision["intent"] == "gui.type_text"


# =========================================================
# SIX FINAL4 FAILURE CLASSES, FRESH WORDING
# =========================================================

def test_class_deterministic_outranked_cross_domain():
    """The final4 taxonomy class, asserted through decide() alone.

    The claim being pinned is that a cross-domain mistake is no longer
    invisible by construction: arbitration is reached, and the
    resolver records the comparison. What the caller holds afterwards
    is the deterministic candidate, because the semantic candidate's
    `destination` precondition cannot be met from a semantic
    decision. Recorded rather than papered over.
    """
    engine = _cross_domain_engine("B")
    decision = engine.decide(CROSS_DOMAIN_REQUEST)
    assert engine._llm_resolver.arbitration_calls == [
        (CROSS_DOMAIN_DET, CROSS_DOMAIN_SEM),
    ]
    assert decision["intent"] == CROSS_DOMAIN_DET


def test_class_same_family_outranked():
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
            "_capability_resolution": {"status": "resolved"},
        },
        "confidence": 0.85, "reason": "synthetic",
    }
    assert engine.decide(
        "go back to the previous track"
    )["intent"] == "media.previous"


def test_class_gate_decline_stays_non_actionable():
    engine = _engine(grounding=None)
    assert engine.decide(
        "can you do something for me"
    )["level"] != 3


def test_class_context_followup_needs_prior_turn():
    engine = _engine(grounding=None)
    assert engine.decide(
        "place that into the reply box"
    )["level"] != 3


def test_class_false_positive_avoided():
    engine = _engine(grounding=None)
    for text in ("how did things finish on friday evening",
                 "who penned the tale of the hunted whale"):
        assert engine.decide(text)["level"] != 3, text


def test_class_wrong_capability_not_fabricated():
    """Arbitration only chooses between two real candidates; it never
    invents an answer where none was produced."""
    engine = _engine(grounding=None, deterministic=None)
    decision = engine.decide(
        "flatten this manuscript into a printable layout"
    )
    assert decision.get("intent") in (None, "document.transform")


# =========================================================
# 16. NO BENCHMARK PHRASE, NO SENTENCE-SPECIFIC RULE
# =========================================================

def test_no_sealed_corpus_phrase_in_code_or_tests():
    sources = [
        BACKEND / "genesis_os" / "llm_intent_resolver.py",
        BACKEND / "genesis_os" / "capability_resolution.py",
        BACKEND / "agents" / "workflow_decision.py",
        BACKEND / "test_phase3_cross_domain_arbitration.py",
        BACKEND / "test_phase3_semantic_grounding.py",
    ]
    raw = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in sources
    )

    def norm(text):
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    collapsed = norm(raw)
    per_line = set()
    for line in raw.splitlines():
        words = norm(line).split()
        for i in range(len(words) - 3):
            per_line.add(tuple(words[i:i + 4]))

    stop = LLMIntentResolver._GROUNDING_STOPWORDS
    checked = 0
    for sealed_name in ("phase3_v3_SEALED.json",
                        "phase3_v4_SEALED.json"):
        sealed_file = BACKEND / sealed_name
        if not sealed_file.exists():
            continue
        sealed = json.loads(sealed_file.read_text(encoding="utf-8"))
        for split in ("dev3", "final3", "dev4", "final4"):
            for item in sealed.get(split, []):
                phrase = item.get("phrase")
                if not phrase:
                    continue
                checked += 1
                words = norm(phrase).split()
                assert " ".join(words) not in collapsed, (
                    f"benchmark phrase reused verbatim: {phrase!r}"
                )
                for start in range(len(words) - 3):
                    run = tuple(words[start:start + 4])
                    if len([w for w in run if w not in stop]) < 2:
                        continue
                    assert run not in per_line, (
                        f"four-word run from a benchmark phrase in the "
                        f"code: {' '.join(run)!r} from {phrase!r}"
                    )
    assert checked > 0


def test_no_request_compared_against_a_literal_phrase():
    request_names = ("text", "request", "anchor", "lowered", "phrase")
    targets = {
        "genesis_os/llm_intent_resolver.py": (
            "lexical_actionability", "evaluate_grounding",
            "grounded_capability", "arbitration_probe",
            "arbitrate_capabilities", "cross_domain_contradiction",
        ),
        "agents/workflow_decision.py": (
            "_arbitrate_os_decision", "_grounded_os_decision",
            "_deterministic_match_is_only_a_hint",
        ),
    }
    checked = 0
    for relative, names in targets.items():
        tree = ast.parse(
            (BACKEND / relative).read_text(encoding="utf-8")
        )
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in names:
            assert name in functions, f"{name} missing from {relative}"
            for node in ast.walk(functions[name]):
                if not isinstance(node, ast.Compare):
                    continue
                operands = [node.left, *node.comparators]
                for operand in operands:
                    if not (isinstance(operand, ast.Constant)
                            and isinstance(operand.value, str)):
                        continue
                    for other in operands:
                        if other is operand:
                            continue
                        if getattr(other, "id", None) in request_names:
                            raise AssertionError(
                                f"{relative}:{name} compares the request "
                                f"against a literal phrase — a "
                                f"sentence-specific rule"
                            )
            checked += 1
    assert checked == 9


def test_no_domain_pair_table_was_hard_coded():
    source = (
        BACKEND / "agents" / "workflow_decision.py"
    ).read_text(encoding="utf-8")
    start = source.index("def _arbitrate_os_decision(")
    body = source[start:source.index("def _grounded_os_decision(", start)]
    tree = ast.parse(body.strip())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if (isinstance(operand, ast.Constant)
                        and isinstance(operand.value, str)
                        and re.match(r"^[a-z_]+\\.[a-z_]+$",
                                     operand.value)):
                    found.append(operand.value)
    assert not found, f"hard-coded capability ids: {found}"
# =========================================================
# THE FIVE NAMED CROSS-DOMAIN CLASSES, FRESH WORDING
# =========================================================
# These are DIAGNOSTIC CATEGORIES from the final4 taxonomy, not
# production rules. Each is expressed here only as a test case with
# its own wording; no domain pair appears in production logic, and
# `test_no_domain_pair_table_was_hard_coded` enforces that.

CROSS_DOMAIN_CASES = [
    ("gui vs clipboard",
     "hold that highlighted fragment on the system clipboard for later",
     "gui.paste_text", "clipboard.copy"),
    ("folder vs file",
     "shift that whole drawer across into my archive area",
     "file.move", "folder.move"),
    ("document vs file",
     "take this manuscript and flatten it into a printable layout",
     "file.copy", "document.transform"),
    ("system vs application",
     "bring up the control panel for machine options",
     "application.open", "system.open_settings"),
    ("spreadsheet vs file",
     "which column of this sheet holds the largest figure",
     "file.search", "spreadsheet.rank"),
]


def test_every_named_cross_domain_class_can_be_arbitrated():
    """All five named domain pairs, at the arbitration layer.

    Each category is checked twice. First the VERDICT, which is the
    taxonomy claim: a cross-domain mistake is no longer invisible,
    because arbitration is reached and selects the semantic candidate.
    Then what the caller actually ends up holding. Those two agree
    only when the semantic capability declares no preconditions; the
    three precondition-bearing pairs keep the deterministic candidate
    because no semantic path supplies inputs. Both outcomes follow
    from the mechanism that produced them, so both are asserted.
    """
    for label, request, deterministic, semantic in CROSS_DOMAIN_CASES:
        # A verbatim proper span of the request, never the whole of it.
        anchor = " ".join(request.split()[1:3])
        grounding = _grounded(request, semantic, anchor)
        assert grounding.grounded is True, label
        assert grounding.discriminative is True, label

        verdict = _resolver(
            grounding=grounding, choice="B", anchor=anchor
        ).arbitrate_capabilities(
            request, _det_intent(deterministic), grounding
        )
        assert verdict.selected == "semantic", label
        assert verdict.selected_source == "semantic", label
        assert verdict.outcome == "semantic_preferred", label

        engine = _engine(
            grounding=grounding,
            choice="B",
            anchor=anchor,
            deterministic=_det_intent(deterministic),
        )
        decision = engine.decide(request)
        if CapabilityRegistry.get(semantic).preconditions:
            assert decision.get("intent") == deterministic, label
        else:
            assert decision.get("intent") == semantic, label
            arbitration = decision["parameters"][
                "_capability_arbitration"
            ]
            assert arbitration["selected"] == "semantic", label


def test_precondition_bearing_semantic_candidate_can_be_selected_but_never_installed():
    """Names the limitation the three cases above rest on.

    Every semantic path builds the promoted decision's `parameters`
    from metadata keys alone, so a semantic candidate's declared
    required inputs are never present and the control plane refuses
    every precondition-bearing promotion. Measured across the
    registry: 17 of 141 capabilities carry preconditions, so for
    those, arbitration can select a candidate but never install it,
    and the deterministic candidate is what the caller gets.

    A real behavioural asymmetry, not a hypothetical: it biases
    cross-domain arbitration toward the deterministic candidate for
    exactly the capabilities that declare inputs. Logged as a future
    item; asserted here so it cannot be forgotten silently.
    """
    from genesis_os.capability_registry import CapabilityRegistry as CR

    registry = CR.operations()
    bearing = {
        capability_id
        for capability_id in registry
        if CR.get(capability_id).preconditions
    }
    assert len(bearing) == 17
    # Registry size guard against silent capability loss. Raised from
    # 141 when system.shutdown / system.restart were registered as
    # classified-but-UNAVAILABLE capabilities, closing the coverage gap
    # where those two operations were invisible to the blast-radius
    # model because they existed only as names in _dangerous_operations.
    assert len(registry) == 143

    engine = WorkflowDecisionEngine()
    promoted = engine._decision(
        level=3, mode="os", task="synthetic", reason="synthetic",
        confidence=0.85, intent="folder.move",
        parameters={"_semantic_resolution": True},
    )
    assert engine._resolve_with_capability_control_plane(promoted) is None
    assert all(
        engine._resolve_with_capability_control_plane(
            engine._decision(
                level=3, mode="os", task="synthetic", reason="synthetic",
                confidence=0.85, intent=capability_id,
                parameters={"_semantic_resolution": True},
            )
        ) is None
        for capability_id in sorted(bearing)
    )


def test_same_family_media_class_still_resolves():
    """Same-family behaviour is the existing hook's job and is
    preserved."""
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
            "_capability_resolution": {"status": "resolved"},
        },
        "confidence": 0.85, "reason": "synthetic",
    }
    assert engine.decide(
        "go back to the previous track"
    )["intent"] == "media.previous"


# =========================================================
# STRUCTURED EVIDENCE IS CAPTURED, NOT FABRICATED
# =========================================================

def test_deterministic_evidence_is_captured_from_the_decision():
    """The previous implementation asserted a single fabricated
    'authoritative, score 1.0' entry, which hid what the arbitration
    needed to compare."""
    request = "shift that whole drawer across into my archive area"
    grounding = _grounded(request, "folder.move",
                          "shift that whole drawer")
    decision = _det_intent("file.move", target="archive area")
    # A realistic deterministic decision carries the control plane's
    # own resolver verdict in `_capability_resolution`; arbitration
    # must carry that through rather than restate it.
    decision["parameters"]["_capability_resolution"] = {
        "status": "resolved",
        "capability_id": "file.move",
        "confidence": 1.0,
        "evidence": [
            {
                "match_type": "exact_capability_id",
                "score": 1.0,
                "reason": "The requested capability ID exactly "
                          "matches a registered Genesis capability.",
            },
        ],
        "alternatives": [],
        "alternatives_count": 0,
    }
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B", "anchor": "shift that whole drawer",
    }
    arbitration = resolver.arbitrate_capabilities(
        request, decision, grounding
    )
    assert arbitration.selected == "semantic"

    match_types = [
        item.match_type for item in arbitration.deterministic_evidence
    ]
    assert "deterministic_candidate" in match_types
    # The resolver's own verdict is carried through, not restated.
    assert "exact_capability_id" in match_types

    payload = arbitration.to_dict()
    assert payload["deterministic_confidence"] == 0.95
    assert payload["deterministic_anchored"] is True
    assert payload["selected_source"] == "semantic"
    assert payload["outcome"] == "semantic_preferred"


def test_risk_level_is_never_used_as_a_relevance_signal():
    """A low-risk capability is not thereby the more correct one.

    Here the SEMANTIC candidate is the riskier of the two and must
    still be selectable, proving risk did not decide the outcome."""
    request = "remove that draft document from my downloads"
    grounding = _grounded(request, "file.delete", "remove that draft")
    assert grounding.grounded is True

    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B", "anchor": "remove that draft",
    }
    arbitration = resolver.arbitrate_capabilities(
        request, _det_intent("folder.organize"), grounding
    )
    assert arbitration.selected == "semantic"
    assert arbitration.risk_level == "critical"


def test_unanchored_deterministic_candidate_is_recorded_as_such():
    request = "shift that whole drawer across into my archive area"
    grounding = _grounded(request, "folder.move",
                          "shift that whole drawer")
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "A", "anchor": "shift that whole drawer",
    }
    arbitration = resolver.arbitrate_capabilities(
        request, _det_intent("file.move", target=None), grounding
    )
    assert arbitration.deterministic_anchored is False
    assert arbitration.selected == "deterministic"


# =========================================================
# WHOLE-REQUEST ANCHOR MUST NOT GROUND
# =========================================================
# Faithfulness is not discriminativeness. A span covering the entire
# request is verbatim for every possible capability.

def test_whole_request_anchor_does_not_ground():
    for request in (
        "can you set this aside for me please",
        "do something with that for me",
        "handle that however you think best",
    ):
        result = _grounded(request, "folder.move", request)
        assert result.grounded is False, request
        assert result.discriminative is False, request
        assert result.strength == 0.0, request
        assert any(
            "discriminates nothing" in reason
            for reason in result.reasons
        ), request


def test_vague_request_with_whole_request_anchor_cannot_override():
    """The measured failure: a vague request accepted at full
    strength when the model quoted it back in full."""
    resolver = LLMIntentResolver(ai_engine=None)
    resolver.arbitration_probe = lambda *a, **k: {
        "choice": "B", "anchor": "can you set this aside for me please",
    }
    weak = _grounded(
        "can you set this aside for me please", "folder.move",
        "can you set this aside for me please",
    )
    arbitration = resolver.arbitrate_capabilities(
        "can you set this aside for me please",
        _det_intent("file.move"), weak,
    )
    assert arbitration.selected == "deterministic"
    assert arbitration.outcome == "rejected"


def test_specific_anchor_still_grounds():
    """The improvement must not break legitimate indirect grounding."""
    result = _grounded(
        "i would like this recorded somewhere permanent",
        "document.create_txt", "recorded somewhere permanent",
    )
    assert result.grounded is True
    assert result.discriminative is True
    assert result.strength > 0


def test_deterministic_still_works_without_a_semantic_challenge():
    engine = _engine(grounding=None,
                     deterministic=_det_intent("workstation.lock"))
    decision = engine.decide("lock the machine before i leave")
    assert decision["intent"] == "workstation.lock"
    assert "_capability_arbitration" not in decision["parameters"]


def test_grounding_still_works_without_a_deterministic_candidate():
    request = "i need this recorded somewhere permanent"
    grounding = _grounded(request, "document.create_txt",
                          "recorded somewhere permanent")
    engine = _engine(grounding=grounding, deterministic=None)
    decision = engine.decide(request)
    assert decision["level"] == 3
    assert decision["intent"] == "document.create_txt"
    assert "_capability_arbitration" not in decision["parameters"]
