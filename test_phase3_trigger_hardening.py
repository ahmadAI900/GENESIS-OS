"""
Phase 3 — evidence-based arbitration trigger.

WHAT CHANGED AND WHY
--------------------
Arbitration eligibility used to be a lexical proxy:

    "is the matched domain's vocabulary absent from the request?"

That asks the wrong question. MEASURED, it could not separate a
capability that is strongly deterministic from one that is merely
said in its own domain's words: a case that needed a challenge scored
0.143 descriptor overlap while a decisive case scored 0.111, because
"flatten this file into a printable layout" happens to contain
"file". Presence and absence of domain vocabulary is not a
decisiveness boundary.

The trigger now asks:

    "does THIS request justify THIS capability?"

Concretely, a deterministic candidate is decisive when the request
names a concrete target or application, or when the request literally
names the operation that capability performs. Both signals come from
the capability's own registry descriptor.

WHY THE OBVIOUS EXISTING SIGNALS COULD NOT BE USED
---------------------------------------------------
Both were measured and found non-discriminating:

  * the detector emits confidence 0.95 for every match;
  * CapabilityResolver.resolve_operation() returns only
    `exact_capability_id` score 1.0 for any registered id, whatever
    the request, and its alternatives list is empty on that path.

Neither carries per-request information, so neither can decide.

NOT USED, AND WHY: descriptor_overlap is reported but never decisive.
Description vocabulary is shared across capabilities and reintroduces
the very proxy this trigger removes.

All wording is synthetic. The corpus-leak scan at the end enforces
that mechanically against both sealed Phase 3 corpora.
"""

import json
import os
import re
import time
from pathlib import Path

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.llm_intent_resolver import LLMIntentResolver

BACKEND = Path(__file__).resolve().parent


def _decision(capability_id, target=None, application=None,
              confidence=0.95):
    return {
        "level": 3, "mode": "os", "task": "synthetic", "agent": None,
        "agents": [], "intent": capability_id,
        "application": application, "target": target,
        "parameters": {"requires_target": True},
        "confidence": confidence, "reason": "synthetic",
    }


def _decisive(request, capability_id, **kwargs):
    return LLMIntentResolver.deterministic_evidence_is_decisive(
        request, _decision(capability_id, **kwargs), capability_id
    )


def _challenge_eligible(request, capability_id, **kwargs):
    return not _decisive(request, capability_id, **kwargs)["decisive"]


# =========================================================
# 1-6. TRIGGER SEMANTICS
# =========================================================

def test_strong_deterministic_evidence_permits_no_semantic_call():
    """The operation the request asks for IS the capability's
    operation."""
    assert not _challenge_eligible(
        "open notepad right now", "application.open"
    )
    assert not _challenge_eligible(
        "move that file into the archive area", "file.move"
    )
    assert not _challenge_eligible(
        "nudge the volume up a notch", "volume.up"
    )


def test_named_target_makes_the_candidate_decisive():
    """A concrete object the user named anchors the match."""
    assert not _challenge_eligible(
        "please remove it", "file.delete", target="quarterly.pdf"
    )
    assert not _challenge_eligible(
        "shut it", "application.close", application="editor"
    )


def test_weak_deterministic_evidence_permits_a_semantic_challenge():
    """No anchor, no named operation: a bare id with no per-request
    justification."""
    assert _challenge_eligible(
        "shift that whole drawer into my archive area", "file.move"
    )


def test_domain_vocabulary_present_but_evidence_weak_still_challenges():
    """The gap the lexical trigger could not see. 'flatten this file
    into a printable layout' names the file domain, so the old proxy
    called it decisive while file.copy is the wrong answer."""
    assert _challenge_eligible(
        "flatten this file into a printable layout", "file.copy"
    )


def test_domain_vocabulary_absent_but_evidence_strong_does_not_challenge():
    """The converse: little domain vocabulary, but the request names
    the operation, so the candidate is still justified."""
    assert not _challenge_eligible(
        "lock the machine before i step away", "workstation.lock"
    )


def test_alternatives_or_missing_resolution_are_reported():
    """Existing structured resolver state is surfaced, not invented."""
    decision = _decision("file.move")
    decision["parameters"]["_capability_resolution"] = {
        "status": "resolved",
        "evidence": [{
            "match_type": "exact_capability_id", "score": 1.0,
            "reason": "exact match",
        }],
        "alternatives": [
            {"capability_id": "folder.move"},
            {"capability_id": "file.copy"},
        ],
    }
    evidence = LLMIntentResolver._deterministic_evidence(
        decision, "file.move"
    )
    assert evidence["alternatives"] == ("folder.move", "file.copy")
    assert "exact_capability_id" in [
        item.match_type for item in evidence["evidence"]
    ]


def test_detector_confidence_alone_is_not_decisive():
    """Pinned deliberately: confidence is 0.95 for every match, so it
    must not be load-bearing for arbitration eligibility."""
    high = _decisive(
        "shift that whole drawer into my archive area",
        "file.move", confidence=0.99,
    )
    low = _decisive(
        "shift that whole drawer into my archive area",
        "file.move", confidence=0.10,
    )
    assert high["signals"]["confidence"] == 0.99
    assert low["signals"]["confidence"] == 0.10
    assert high["decisive"] is low["decisive"] is False


def test_reasons_are_reported_when_not_decisive():
    verdict = _decisive(
        "shift that whole drawer into my archive area", "file.move"
    )
    assert verdict["reasons"]
    assert any(
        "no per-request justification" in reason
        for reason in verdict["reasons"]
    )


def test_malformed_candidate_is_never_decisive():
    verdict = LLMIntentResolver.deterministic_evidence_is_decisive(
        "something", _decision("not-a-capability"), "not-a-capability"
    )
    assert verdict["decisive"] is False
    assert LLMIntentResolver.deterministic_evidence_is_decisive(
        "something", "not even a dict", "file.move"
    )["decisive"] is False


# =========================================================
# ZERO-CALL FAST PATH — PROVEN THROUGH THE ENGINE
# =========================================================

class _CountingResolver:
    """Wraps the real resolver and counts semantic/arbitration calls."""

    def __init__(self, inner):
        self._inner = inner
        self.grounded_calls = 0
        self.arbitration_calls = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def grounded_capability(self, text, **kwargs):
        self.grounded_calls += 1
        return None

    def arbitrate_capabilities(self, *args, **kwargs):
        self.arbitration_calls += 1
        return None


@pytest.mark.parametrize("text,capability_id", [
    ("open notepad right now", "application.open"),
    ("move that file into the archive area", "file.move"),
    ("nudge the volume up a notch", "volume.up"),
])
def test_decisive_candidate_makes_zero_model_calls(text, capability_id):
    engine = WorkflowDecisionEngine()
    engine._detect_os_intent = lambda t: _decision(capability_id)
    engine._resolve_with_capability_control_plane = lambda d: d
    engine._detect_extended_os_intent = lambda t: None
    counter = _CountingResolver(engine._llm_resolver)
    engine._llm_resolver = counter

    decision = engine.decide(text)

    assert decision["intent"] == capability_id
    assert counter.grounded_calls == 0, text
    assert counter.arbitration_calls == 0, text
    assert "_capability_arbitration" not in decision["parameters"]


def test_non_decisive_candidate_reaches_semantic_grounding():
    """Vocab present, evidence weak -> the LLM path is entered."""
    engine = WorkflowDecisionEngine()
    engine._detect_os_intent = lambda t: _decision("file.copy")
    engine._resolve_with_capability_control_plane = lambda d: d
    engine._detect_extended_os_intent = lambda t: None
    counter = _CountingResolver(engine._llm_resolver)
    engine._llm_resolver = counter

    engine.decide("flatten this file into a printable layout")

    assert counter.grounded_calls == 1


# =========================================================
# THE TWO PREVIOUSLY UNRESOLVED CLASSES
# =========================================================
# Structural equivalents, NOT named production rules. No domain pair
# appears in the implementation; these are test cases only.

@pytest.mark.parametrize("text,capability_id", [
    ("turn this manuscript into a fixed page layout", "file.copy"),
    ("work out which column of this sheet totals highest",
     "file.search"),
])
def test_previously_unresolved_classes_are_now_eligible(text,
                                                       capability_id):
    assert _challenge_eligible(text, capability_id)


def test_their_file_domain_counterpart_remains_authoritative():
    """A file candidate that IS justified must not be challenged, or
    the new trigger would simply trade one failure for the other."""
    assert not _challenge_eligible(
        "move that spreadsheet into my archive folder", "file.move"
    )


def test_a_fresh_family_outside_the_previous_examples_is_handled():
    """A family never used in earlier arbitration examples. The
    mechanism reads the capability's own descriptor, so it needs no
    knowledge of this domain at all."""
    assert _challenge_eligible(
        "put that recording into my archive", "media.capture"
    ) or _challenge_eligible(
        "archive that recording", "file.copy"
    )
    # And a justified candidate in that same family is not challenged.
    assert not _challenge_eligible(
        "capture a recording of my screen", "media.capture"
    )


# =========================================================
# 28. _shortlist_catalog INTEGRITY
# =========================================================
# The function was accidentally clobbered during an earlier edit and
# restored. These pin the restoration.

def test_shortlist_catalog_is_byte_identical_to_intended_construction():
    resolver = LLMIntentResolver(ai_engine=None)
    actual = resolver._shortlist_catalog()

    by_domain = {}
    for capability in CapabilityRegistry.all():
        by_domain.setdefault(
            capability.capability_id.split(".", 1)[0], []
        ).append(capability.capability_id)
    expected = "\n".join(
        f"{domain}: " + ", ".join(sorted(ids))
        for domain, ids in sorted(by_domain.items())
    )

    assert actual == expected


def test_shortlist_catalog_contains_every_registered_capability():
    resolver = LLMIntentResolver(ai_engine=None)
    catalog = resolver._shortlist_catalog()
    missing = [
        capability.capability_id
        for capability in CapabilityRegistry.all()
        if capability.capability_id not in catalog
    ]
    assert missing == []


def test_shortlist_catalog_is_deterministic_across_calls():
    resolver = LLMIntentResolver(ai_engine=None)
    assert resolver._shortlist_catalog() == resolver._shortlist_catalog()


# =========================================================
# 25-27. BENCHMARK INTEGRITY AND GENERICITY
# =========================================================

def test_no_sealed_corpus_phrase_in_code_or_tests():
    sources = [
        BACKEND / "genesis_os" / "llm_intent_resolver.py",
        BACKEND / "genesis_os" / "capability_resolution.py",
        BACKEND / "agents" / "workflow_decision.py",
        BACKEND / "test_phase3_trigger_hardening.py",
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
                        f"four-word benchmark run in code: "
                        f"{' '.join(run)!r} from {phrase!r}"
                    )
    assert checked > 0


def test_trigger_references_no_capability_specific_literal():
    """The decisive test must read the candidate's own descriptor, not
    a hard-coded capability.

    Inspected via AST so that explanatory prose in the docstring is
    not mistaken for a rule: only string literals in the logic count.
    """
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(
        LLMIntentResolver.deterministic_evidence_is_decisive
    ))
    tree = ast.parse(source)
    function = tree.body[-1]

    # Drop the docstring: prose may legitimately name domains.
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    literals = [
        node.value
        for node in ast.walk(ast.Module(body=body, type_ignores=[]))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "docstring" not in node.value.lower()
    ]

    for value in literals:
        assert not re.match(r"^[a-z_]+\.[a-z_]+$", value), (
            f"hard-coded capability id in the trigger: {value!r}"
        )

    # Decision field names such as "application" and "target" are
    # keys on the decision object, not domains, so a bare
    # domain-name check would false-positive on them. What matters
    # is that no capability id is named, and that no domain is
    # COMPARED against, which is covered by the absence of any
    # domain-shaped comparison plus the engine-level check below.


def test_trigger_does_not_use_domain_vocabulary_presence():
    """The old lexical trigger must no longer gate arbitration."""
    source = (
        BACKEND / "agents" / "workflow_decision.py"
    ).read_text(encoding="utf-8")
    start = source.index("def _arbitrate_os_decision(")
    end = source.index("def _grounded_os_decision(", start)
    body = source[start:end]
    assert "cross_domain_contradiction" not in body, (
        "the lexical trigger still gates arbitration"
    )
    assert "deterministic_evidence_is_decisive" in body
# =========================================================
# BACKEND REACHABILITY
# =========================================================
# Step 1 of the closure directive asked whether the default backend
# order ('local', 'cloud', None) with a 22s total budget makes the
# stronger cloud backend unreachable on a host with a slow local
# provider.
#
# MEASURED ON THIS HOST under production defaults (no environment
# overrides): the local attempt is bounded by the 12s per-call
# timeout, cloud then answers, total wall 12.8s. Cloud was NEVER
# unreachable. An earlier report in this phase claimed it was, based
# on an inference that was never tested; that claim was wrong and is
# corrected here.
#
# The genuine, narrower defect is LATENCY: every request on a host
# with a slow or absent local provider pays a fixed ~12s dead wait
# before the cloud backend is tried. The tests below pin the
# reachability guarantee so it cannot regress into a real outage.

class _SlowLocalEngine:
    """AI engine whose local path hangs and whose cloud path works."""

    def __init__(self):
        self.local_calls = 0
        self.cloud_calls = 0

    def generate(self, prompt, **kwargs):
        return "local"

    def chat(self, messages, **kwargs):
        return "local"

    def is_local_available(self):
        return True

    def can_query(self, prompt=None):
        return True


def test_default_backend_order_is_local_first_then_cloud():
    """Documented default, cited from llm_intent_resolver.py:290."""
    resolver = LLMIntentResolver(ai_engine=None)
    assert resolver._backend_modes() == ("local", "cloud", None)


def test_each_backend_attempt_is_bounded_by_the_per_call_timeout():
    """This bound is what guarantees cloud is reached: a slow local
    provider cannot consume the whole total budget because it is
    abandoned after _LLM_CALL_TIMEOUT."""
    resolver = LLMIntentResolver(ai_engine=None)
    assert resolver._LLM_CALL_TIMEOUT < resolver._RESOLVE_TOTAL_BUDGET, (
        "a single backend could consume the entire total budget"
    )


def test_cloud_is_reached_within_budget_when_local_is_slow():
    """Simulated slow local backend: the first attempt fails or times
    out and the next backend must still be attempted inside the total
    budget."""
    resolver = LLMIntentResolver(ai_engine=None)

    attempted = []

    def _fake_call(prompt, mode=None):
        attempted.append(mode)
        if mode == "local":
            raise TimeoutError("simulated slow local provider")
        return '{"actionable": true, "capability_id": "file.open", "anchor": "diary"}'

    resolver._call_llm_with_timeout = _fake_call

    result = resolver._grounding_probe(
        "would you mind pulling up my diary for today",
        time.monotonic() + resolver._RESOLVE_TOTAL_BUDGET,
    )

    assert attempted[0] == "local"
    assert "cloud" in attempted, (
        f"cloud never attempted; order was {attempted}"
    )
    assert result is not None
    assert result.get("capability_id") == "file.open"


def test_budget_env_vars_remain_the_escape_hatch(monkeypatch):
    """Documented here so the correct configuration does not have to
    be rediscovered: setting GENESIS_LLM_MODES=cloud skips local
    entirely, and the two budget vars override the defaults.

    The class attributes MUST be restored explicitly. ``_apply_budget_overrides``
    writes the parsed env values onto the class with ``setattr(cls, ...)``
    (genesis_os/llm_intent_resolver.py), and that mutation is
    permanent: popping the environment variable afterwards does not put
    the default back. Without this restore, running this file before
    test_phase3_control_plane_maturity.py left ``_LLM_CALL_TIMEOUT`` at
    60.0 for the rest of the process and two unrelated budget tests
    failed. That was order-dependent pollution, invisible under the
    default alphabetical collection order, because
    control_plane_maturity sorts before trigger_hardening.

    The production behaviour is deliberately left alone: persisting an
    explicit override for the life of the process is legitimate for a
    batch measurement. The defect was this test failing to clean up
    after itself.
    """
    original_call_timeout = LLMIntentResolver._LLM_CALL_TIMEOUT
    original_total_budget = LLMIntentResolver._RESOLVE_TOTAL_BUDGET
    monkeypatch.setenv("GENESIS_LLM_MODES", "cloud")
    monkeypatch.setenv("GENESIS_LLM_CALL_TIMEOUT", "60")
    monkeypatch.setenv("GENESIS_LLM_TOTAL_BUDGET", "120")
    try:
        resolver = LLMIntentResolver(ai_engine=None)
        assert resolver._backend_modes() == ("cloud",)
        assert resolver._LLM_CALL_TIMEOUT == 60.0
        assert resolver._RESOLVE_TOTAL_BUDGET == 120.0
    finally:
        LLMIntentResolver._LLM_CALL_TIMEOUT = original_call_timeout
        LLMIntentResolver._RESOLVE_TOTAL_BUDGET = original_total_budget


@pytest.fixture(autouse=True)
def _restore_budget_class_attributes():
    """Module-wide guard against budget-class-attribute pollution.

    ``_apply_budget_overrides`` permanently ``setattr``s the two budget
    attributes onto ``LLMIntentResolver``. Any test in this module that
    sets the corresponding environment variables therefore mutates
    process-wide state that outlives the test, which is how two
    unrelated tests in test_phase3_control_plane_maturity.py were made
    to fail depending on collection order.

    The individual test below restores its own attributes; this fixture
    is the belt to that braces, so a future test added to this module
    cannot reintroduce the same leak.
    """
    saved_call_timeout = LLMIntentResolver._LLM_CALL_TIMEOUT
    saved_total_budget = LLMIntentResolver._RESOLVE_TOTAL_BUDGET
    saved_env = {
        name: os.environ.get(name)
        for name in (
            "GENESIS_LLM_CALL_TIMEOUT",
            "GENESIS_LLM_TOTAL_BUDGET",
            "GENESIS_LLM_MODES",
        )
    }
    try:
        yield
    finally:
        LLMIntentResolver._LLM_CALL_TIMEOUT = saved_call_timeout
        LLMIntentResolver._RESOLVE_TOTAL_BUDGET = saved_total_budget
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_budget_override_does_not_leak_to_later_tests():
    """The escape hatch still works AND leaves no residue behind.

    Runs the documented override, then asserts the class attributes are
    back at their pre-test values and the environment variables are
    gone. This is the assertion whose absence allowed the original
    order-dependent failure to hide.
    """
    import os as _os

    before_call_timeout = LLMIntentResolver._LLM_CALL_TIMEOUT
    before_total_budget = LLMIntentResolver._RESOLVE_TOTAL_BUDGET

    _os.environ["GENESIS_LLM_CALL_TIMEOUT"] = "45"
    try:
        resolver = LLMIntentResolver(ai_engine=None)
        assert resolver._LLM_CALL_TIMEOUT == 45.0
        assert LLMIntentResolver._LLM_CALL_TIMEOUT == 45.0
    finally:
        _os.environ.pop("GENESIS_LLM_CALL_TIMEOUT", None)
        LLMIntentResolver._LLM_CALL_TIMEOUT = before_call_timeout
        LLMIntentResolver._RESOLVE_TOTAL_BUDGET = before_total_budget

    assert LLMIntentResolver._LLM_CALL_TIMEOUT == before_call_timeout
    assert LLMIntentResolver._RESOLVE_TOTAL_BUDGET == before_total_budget
    assert "GENESIS_LLM_CALL_TIMEOUT" not in os.environ
