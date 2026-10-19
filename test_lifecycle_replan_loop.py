"""
ITEM 18C (L18) -- the replan loop must enclose verification.

runtime/genesis_runtime.py execute_with_lifecycle() had:

    while replan_count <= max_replans:
        try:
            exec_result = engine.execute(...)
            break
        except ...: ...
    # OBSERVE & VERIFY lived OUTSIDE the loop
    ...
    if classification.retryable and replan_count < max_replans:
        recovery_log.append({... "attempt": ...})
        replan_count += 1
        # Continue loop for replan     <- fell through; no loop
    _record_phase(FAILED, "lifecycle_incomplete_fallback")

A retryable verification failure (classify("Verification failed",
first-step operation) is retryable when the operation starts with
"browser.") therefore executed the plan EXACTLY ONCE, logged a
recovery attempt that never ran, incremented a counter no loop ever
saw, and fell through to the generic fallback with an empty result
instead of the honest verification_failed_final terminal.

The fix encloses execution AND verification in the loop (Option 1
from the directive): verification failure now really replans until
max_replans, and exhaustion ends at verification_failed_final. The
loop re-executes the current plan object, exactly like the
pre-existing exception-path "replan" always did (no planner
regeneration exists in this method).
"""
import ast
import textwrap
from inspect import getsource
from unittest.mock import MagicMock

from genesis_os.action_plan import ActionPlan
from genesis_os.workflow_models import WorkflowPlan, WorkflowStep
from runtime.genesis_runtime import GenesisRuntime

MAX_REPLANS = 2  # execute_with_lifecycle default


def make_runtime():
    runtime = GenesisRuntime(
        brain=MagicMock(),
        conversation=MagicMock(),
        memory=MagicMock(),
        ai_engine=MagicMock(),
        agent_bridge=MagicMock(),
        os_manager=None,
    )
    runtime.agent_bridge.handle.return_value = {"status": "completed"}
    runtime.agent_bridge.classify_request.return_value = {
        "type": "agent",
        "agent": "test_agent",
    }
    return runtime


def make_plan(operation="browser.open_url"):
    step = WorkflowStep(
        step_id="step-1",
        plan=ActionPlan(
            operation=operation,
            target="https://example.com"
            if operation.startswith("browser.")
            else "Notepad",
            application="browser"
            if operation.startswith("browser.")
            else "Notepad",
            confidence=1.0,
        ),
    )
    return WorkflowPlan(
        objective="test objective",
        steps=(step,),
        workflow_id="wf-test-18c",
    )


def make_result(verified):
    result = MagicMock()
    result.trustworthy_success = verified
    result.to_dict.return_value = {
        "success": bool(verified),
        "status": "verified" if verified else "verification_failed",
    }
    return result


def engine_returning(*results):
    engine = MagicMock()
    engine.execute.side_effect = list(results)
    return engine


def run(engine, operation="browser.open_url", max_replans=MAX_REPLANS):
    runtime = make_runtime()
    runtime._workflow_engine = engine
    out = runtime.execute_with_lifecycle(
        "navigate to the page",
        workflow_plan=make_plan(operation),
        max_replans=max_replans,
    )
    events = [p.get("event") for p in out["phases"]]
    return out, events


def test_verification_failure_retries_up_to_max_replans():
    engine = engine_returning(
        make_result(False),
        make_result(False),
        make_result(False),
    )

    out, events = run(engine)

    assert engine.execute.call_count == 1 + MAX_REPLANS, (
        f"execute ran {engine.execute.call_count} times; a retryable "
        f"verification failure must use all {MAX_REPLANS} replans"
    )
    assert out["success"] is False
    assert "verification_failed_final" in events


def test_verification_failure_recovers_on_retry():
    engine = engine_returning(
        make_result(False),
        make_result(True),
    )

    out, events = run(engine)

    assert engine.execute.call_count == 2
    assert out["success"] is True
    assert "lifecycle_complete" in events


def test_exhausted_verification_failure_is_an_honest_terminal():
    engine = engine_returning(
        make_result(False),
        make_result(False),
        make_result(False),
    )

    out, events = run(engine)

    assert events[-1] == "verification_failed_final"
    assert "lifecycle_incomplete_fallback" not in events
    assert out["success"] is False
    assert out["result"] == {
        "success": False,
        "status": "verification_failed",
    }


def test_recovery_attempts_are_real():
    engine = engine_returning(
        make_result(False),
        make_result(False),
        make_result(False),
    )

    out, _events = run(engine)

    recovery = out["recovery"]
    assert [entry["attempt"] for entry in recovery] == [1, 2]
    assert engine.execute.call_count == len(recovery) + 1, (
        "every logged recovery attempt must correspond to an actual "
        "extra engine.execute call"
    )


def test_retry_phases_recorded_per_attempt():
    engine = engine_returning(
        make_result(False),
        make_result(False),
        make_result(False),
    )

    _out, events = run(engine)

    assert events.count("verification_failed") == 1 + MAX_REPLANS
    assert events.count("verification_recovery") == MAX_REPLANS
    assert events.count("attempting_replan") == MAX_REPLANS


def test_ast_while_loop_encloses_execute_and_verify():
    source = getsource(GenesisRuntime.execute_with_lifecycle)
    tree = ast.parse(textwrap.dedent(source))
    lines = source.splitlines()

    loops = [
        "\n".join(lines[node.lineno - 1:node.end_lineno])
        for node in ast.walk(tree)
        if isinstance(node, ast.While)
        and "_workflow_engine.execute" in
        "\n".join(lines[node.lineno - 1:node.end_lineno])
    ]

    assert loops, "no while loop containing engine.execute found"
    loop_source = loops[0]
    assert "trustworthy_success" in loop_source, (
        "verification (trustworthy_success) is outside the replan loop"
    )
    assert "verification_failed_final" in loop_source, (
        "the honest terminal is outside the replan loop"
    )


def test_source_no_longer_claims_loop_continuation_without_a_loop():
    source = getsource(GenesisRuntime.execute_with_lifecycle)

    assert "# Continue loop for replan" not in source, (
        "the comment still claims loop continuation for a "
        "fall-through path"
    )


def test_verified_result_first_attempt_returns_success():
    engine = engine_returning(make_result(True))

    out, events = run(engine)

    assert engine.execute.call_count == 1
    assert out["success"] is True
    assert events[-1] == "lifecycle_complete"


def test_none_execution_result_still_falls_back():
    engine = engine_returning(None)

    out, events = run(engine)

    assert out["success"] is False
    assert out["error"] == (
        "Workflow lifecycle ended without a verified result."
    )
    assert out["result"] == {}
    assert events[-1] == "lifecycle_incomplete_fallback"


def test_non_retryable_verification_failure_does_not_retry():
    engine = engine_returning(
        make_result(False),
        make_result(True),
    )

    out, events = run(engine, operation="application.open")

    assert engine.execute.call_count == 1, (
        "a non-retryable classification must not re-execute"
    )
    assert events[-1] == "verification_failed_final"
    assert out["success"] is False


def test_max_replans_zero_skips_retries():
    engine = engine_returning(
        make_result(False),
        make_result(True),
    )

    out, events = run(engine, max_replans=0)

    assert engine.execute.call_count == 1
    assert events[-1] == "verification_failed_final"
    assert out["success"] is False
