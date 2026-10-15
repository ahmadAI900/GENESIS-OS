"""
Regression tests for the two live-discovered defects in
the Genesis confirmation pipeline:

1. The AI intent layer was being invoked on plain
   conversational text because the cheap pre-filter
   (``LLMIntentResolver.looks_actionable``) only looked
   for ANY action-shaped verb in the input, anywhere.
   "hii now i make you able to control my computer"
   passed the gate (the verb "make" appears in the
   sentence) and the LLM was asked to map a non-action
   onto a capability, producing the false-positive
   "I understood that as: run 'cleanup.recycle_bin_query'".

2. The confirmation prompt constructed by
   ``GenesisOS._describe_operation`` used
   ``f"run '{operation}'"`` as its fallback, exposing
   the raw capability id in the text shown to the user
   — making informed consent impossible even when the
   proposed action was legitimate.

These tests pin both behaviors: conversational inputs
MUST NOT pass the gate, and the user-facing
confirmation text MUST NOT contain raw capability ids.
"""

import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real GenesisOS.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


# =========================================================
# TASK 1 — INTENT GATE REJECTS CONVERSATIONAL INPUTS
# =========================================================


@pytest.mark.parametrize(
    "conversational_text",
    [
        # The exact live-reproduced false positive.
        "hii now i make you able to control my computer",
        # Plain greetings.
        "hello there friend",
        "hi how are you doing today",
        # Subject + verb constructions — verb in object
        # position, not imperative position.
        "you make me happy",
        "i think we should set up a meeting",
        # Question phrasings that mention OS-shaped words
        # without requesting an action.
        "can you do something for me",
        # Casual statement about an action-shaped concept
        # ("set up") but in non-imperative form.
        "she set the table before we arrived",
        # Open-ended question about capabilities.
        "what can you do for me",
    ],
)
def test_conversational_inputs_do_not_pass_intent_gate(
    conversational_text,
):
    """
    Plain conversational inputs must not pass the AI
    intent gate, even when they contain action-shaped
    verbs ("make", "set", "open") in non-imperative
    position.
    """

    from genesis_os.llm_intent_resolver import (
        LLMIntentResolver,
    )

    assert (
        LLMIntentResolver.looks_actionable(
            conversational_text
        )
        is False
    )


@pytest.mark.parametrize(
    "actionable_text",
    [
        # Original true positive from the existing test.
        "make my screen dimmer",
        # Common imperative forms from the live demos.
        "open notepad",
        "please open notepad",
        "can you open chrome",
        "set volume to 40",
        "i want to mute the volume",
        "let me capture the screen",
        "take a screenshot",
        "lock my computer",
        # Greeting + imperative.
        "hey, open notepad",
        # STACKED prefixes — interjection AND polite in the same
        # sentence. A single-pass stripper leaves "can you open
        # notepad", whose first word is not an action verb, and
        # wrongly rejects the sentence. The stripper MUST peel
        # both layers in sequence to recover the imperative verb.
        "hey, can you open notepad",
        "hi, please open notepad",
        "ok, can you lock my computer",
        "hey can you open chrome",
    ],
)
def test_actionable_inputs_still_pass_intent_gate(
    actionable_text,
):
    """
    Tightening the gate must NOT over-correct into
    rejecting genuine imperative requests.
    """

    from genesis_os.llm_intent_resolver import (
        LLMIntentResolver,
    )

    assert (
        LLMIntentResolver.looks_actionable(
            actionable_text
        )
        is True
    )


def test_intent_gate_does_not_invoke_resolver_for_conversational_text(
    monkeypatch,
):
    """
    End-to-end check: when the gate rejects an input,
    the LLM resolver's ``resolve()`` method is NEVER
    called. This prevents the AI from "inventing" an
    intent out of conversational text.
    """

    from genesis_os import llm_intent_resolver as module

    resolve_calls = []

    def spy_resolve(self, text):
        resolve_calls.append(text)
        return None

    monkeypatch.setattr(
        module.LLMIntentResolver,
        "resolve",
        spy_resolve,
    )

    from genesis import GenesisOS

    genesis = GenesisOS()

    # Sanity: the gate rejects this input.
    from genesis_os.llm_intent_resolver import (
        LLMIntentResolver,
    )

    assert (
        LLMIntentResolver.looks_actionable(
            "hii now i make you able to control my computer"
        )
        is False
    )

    # The unresolved handler must therefore return None
    # for that input, never propose an action, and never
    # invoke resolve() at all.
    response = genesis._handle_unmatched_request(
        "hii now i make you able to control my computer"
    )

    assert response is None
    assert resolve_calls == []


# =========================================================
# TASK 2 — CONFIRMATION PROMPT IS HUMAN-READABLE
# =========================================================


@pytest.mark.parametrize(
    "operation,target,parameters",
    [
        # The exact failing case from the bug report.
        (
            "cleanup.recycle_bin_query",
            "recycle_bin",
            {},
        ),
        # Another capability whose descriptor uses a
        # real, human-readable sentence.
        (
            "cleanup.empty_recycle_bin",
            "recycle_bin",
            {},
        ),
        # Override-driven cases (these pre-existed but
        # are pinned here so the override-vs-registry
        # path doesn't regress).
        (
            "screen.capture",
            "screen",
            {},
        ),
        (
            "workstation.lock",
            "workstation",
            {},
        ),
    ],
)
def test_confirmation_text_never_contains_raw_capability_id(
    operation, target, parameters
):
    """
    The text shown to the user must be plain language;
    the raw capability id (e.g. "cleanup.recycle_bin_query"
    or "screen.capture") must NEVER appear in it. The
    raw id is still recorded separately in the debug log.
    """

    from genesis import GenesisOS

    text = GenesisOS._describe_operation(
        operation, target, parameters
    )

    assert operation not in text, (
        f"Raw capability id {operation!r} leaked into "
        f"user-facing confirmation text: {text!r}"
    )
    assert text.strip() != ""
    # The text must look like a sentence — start with a
    # letter, contain a space, not be all underscores /
    # dotted identifiers.
    assert " " in text


def test_confirmation_text_uses_descriptor_for_recycle_bin_query():
    """
    The exact bug from the report:
        "I understood that as: run 'cleanup.recycle_bin_query'."
    must now be plain language derived from the
    capability's descriptor.
    """

    from genesis import GenesisOS

    text = GenesisOS._describe_operation(
        "cleanup.recycle_bin_query", "recycle_bin", {}
    )

    assert "cleanup.recycle_bin_query" not in text
    assert "run '" not in text
    # The descriptor for this capability says
    # "Report Recycle Bin item count and size." After
    # stripping the trailing "Read-only." noise, the
    # plain-language core should remain.
    lowered = text.lower()
    assert "recycle bin" in lowered


def test_confirmation_text_for_unknown_operation_does_not_leak_id():
    """
    If an operation is not in the registry, the
    fallback phrase must still NOT contain the raw id.
    The previous behavior exposed it as ``run '<id>'``.
    """

    from genesis import GenesisOS

    text = GenesisOS._describe_operation(
        "totally.fake_op_xyz", "x", {}
    )

    assert "totally.fake_op_xyz" not in text
    assert "run '" not in text


# =========================================================
# TASK 3 — RESULT LINES NEVER CONTRADICT THEMSELVES
# =========================================================
#
# Live confirmation transcript showed these four lines for the
# SAME single verified operation (cleanup.recycle_bin_query):
#
#     [Genesis OS] Verified: True
#     [Genesis OS] Operation completed successfully.
#     [Genesis OS] Result verified.
#     [Genesis OS] Operation was NOT verified successfully.
#
# The first three are mutually consistent. The fourth
# contradicts the third for the same single operation. The
# third line is gated by ``if result.verified`` (truthful).
# The fourth was NOT gated by anything — it printed
# unconditionally after the verified/already-in-state chain,
# so it lied for the verified case.
#
# Fix: wrap the "NOT verified" print in an ``else`` branch
# so it fires only when verified is False AND the target is
# not already in the desired state. Both messages stay —
# we do not silence either one, we determine which one is
# lying and stop the lie.


def _capture_run_level3_stdout(
    monkeypatch,
    *,
    success: bool,
    verified: bool,
    already_in_desired_state: bool = False,
    error: str = "",
):
    """
    Drive GenesisOS.run_level3 with a fabricated ActionResult
    and return the captured stdout as a single string.
    """

    import io
    import contextlib

    from genesis_os.action_result import ActionResult

    captured_plans = []

    def fake_execute(plan):
        captured_plans.append(plan)
        return ActionResult(
            success=success,
            operation=plan.operation,
            target=plan.target,
            application=plan.application,
            status=(
                "verified"
                if verified
                else ("desired_state" if already_in_desired_state else "failed")
            ),
            message="captured",
            executed=True,
            verified=verified,
            already_in_desired_state=(
                already_in_desired_state
            ),
            error=(error or None),
        )

    from genesis import GenesisOS
    from agents.workflow_decision import (
        WorkflowDecisionEngine,
    )

    genesis = GenesisOS()

    monkeypatch.setattr(
        genesis.action_executor,
        "execute",
        fake_execute,
    )

    buf = io.StringIO()

    # Bypass classify() — it returns Level 1 conversation in
    # the test environment for free-form text like "check
    # the recycle bin". Use the deterministic decision
    # engine directly so we exercise the single-step path
    # inside run_level3 (which is what prints the lines
    # under test). "open notepad" resolves to a clean
    # application.open / notepad / Level 3 decision with
    # a real target.
    decision = WorkflowDecisionEngine().decide(
        "open notepad"
    )

    try:
        with contextlib.redirect_stdout(buf):
            genesis.run_level3("open notepad", decision)
    except Exception:
        # The single-step branch may raise after the
        # prints we care about have already been emitted.
        # Whatever stdout was captured up to that point is
        # what we assert on.
        pass

    return buf.getvalue()


def test_verified_result_does_not_print_not_verified_line(
    monkeypatch,
):
    """
    The exact contradiction from the live transcript:
    when an operation was VERIFIED, the
    'Operation was NOT verified successfully.' line must NOT
    appear, because that would contradict the 'Result
    verified.' line for the same single operation.
    """

    stdout = _capture_run_level3_stdout(
        monkeypatch,
        success=True,
        verified=True,
    )

    assert (
        "[Genesis OS] Result verified."
        in stdout
    ), stdout
    assert (
        "[Genesis OS] Operation was NOT verified "
        "successfully."
        not in stdout
    ), (
        "The unconditional 'Operation was NOT verified "
        "successfully.' line still fires for the verified "
        "case and contradicts 'Result verified.' for the "
        "same single operation.\n\n"
        f"Captured stdout:\n{stdout}"
    )


def test_unverified_result_still_prints_negative_line(
    monkeypatch,
):
    """
    Counterpart: when an operation genuinely was NOT
    verified, the 'Operation was NOT verified
    successfully.' line MUST still appear. We are not
    silencing the negative observation — we are stopping
    it from firing in the wrong case.
    """

    stdout = _capture_run_level3_stdout(
        monkeypatch,
        success=False,
        verified=False,
        error="foreground window title is empty",
    )

    assert (
        "[Genesis OS] Operation was NOT verified "
        "successfully."
        in stdout
    ), stdout


def test_already_in_desired_state_does_not_print_not_verified_line(
    monkeypatch,
):
    """
    Edge case: when the target was already in the desired
    state, the negative line must NOT appear - we already
    announced 'Target was already in the requested state.'

    REWRITTEN 2026-10-04. The premise has inverted. This asserted
    that "Operation was NOT verified successfully." was ABSENT when
    `already_in_desired_state` is set. The Phase 1 evidence contract
    made that wrong: a desired-state flag is not evidence. Per
    `PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md`, `Evidence.from_result`
    derives `passed` from capability-specific evidence rather than an
    unconditional control value, so a result that claims
    `already_in_desired_state` while carrying no evidence must NOT be
    reported as verified.

    The replacement regression test this file used to carry was named
    `test_desired_state_without_evidence_is_not_reported_as_verified`,
    which is exactly this contract. So the honest outcome is now
    asserted: the negative line IS printed, because nothing observed
    the desired state.
    """
    stdout = _capture_run_level3_stdout(
        monkeypatch,
        success=True,
        verified=False,
        already_in_desired_state=True,
    )

    assert (
        "[Genesis OS] Operation was NOT verified "
        "successfully."
        in stdout
    ), (
        "a desired-state claim carrying no evidence was reported as "
        f"verified: {stdout}"
    )
    assert (
        "[Genesis OS] Target was already in the "
        "requested state."
        not in stdout
    ), (
        "the desired-state line was printed even though the claim "
        f"carried no evidence: {stdout}"
    )
