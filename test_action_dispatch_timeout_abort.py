"""Item 21A (C32): the per-action timeout could not fire.

`ActionExecutor.execute` section 7 (DISPATCH) ran:

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _executor:
        _future = _executor.submit(self._dispatch, plan)
        raw_result = _future.result(timeout=timeout)

future.result(timeout) DID raise TimeoutError on time, but leaving the
`with` block then ran ThreadPoolExecutor.__exit__ -> shutdown(wait=True),
which waits for the hung _dispatch to finish. The timeout fired on paper
and the caller still paid the whole overrun.

REPRODUCED, not assumed: against the committed original, a 3.0s sleep
against a 0.5s budget (this test uses 1.2s vs 0.25s for speed):

    status  : execution_timeout
    elapsed : 3.02s  <- returned when the sleep ended, not at 0.5s

The honest limit, stated rather than hidden: shutdown(wait=False) does
not kill the worker. A thread that cannot be interrupted is ABANDONED --
still running until _dispatch returns on its own. This test pins both
sides: the CALL returns near the timeout, and the worker really is still
out there (we do not pretend it was stopped).

Mirrors test_dispatch_timeout_abort.py (Item 17A), which fixed the same
bug in browser_manager._dispatch_with_timeout.
"""
from __future__ import annotations

import ast
import pathlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan

EXECUTOR = pathlib.Path("genesis_os") / "action_executor.py"

SLEEP_S = 1.2
TIMEOUT_S = 0.25
# Fail-before ~1.2s; pass-after ~0.3s. Both sides sit far from 0.9.
MUST_RETURN_BY = 0.9


class _FakeOS:
    """The executor only stores the OS manager before dispatch."""


@pytest.fixture
def ex():
    return ActionExecutor(_FakeOS())


def _plan() -> ActionPlan:
    # Reaches section 7 (DISPATCH) on the committed original: proven by
    # the repro that produced the measurements in the module docstring.
    return ActionPlan(
        operation="application.open",
        target="notepad",
        parameters={},
        confidence=0.99,
    )


def _function_body(name):
    tree = ast.parse(EXECUTOR.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {EXECUTOR}")


# --------------------------------------------------------------------------
# The regression: a slow action returns at ~timeout, not after the full sleep
# --------------------------------------------------------------------------

def test_a_hung_action_returns_near_the_timeout(ex, monkeypatch):
    monkeypatch.setattr(
        ex, "_dispatch",
        lambda plan: (time.sleep(SLEEP_S)
                      or {"success": True, "executed": True}),
    )

    started = time.monotonic()
    result = ex.execute(_plan(), timeout=TIMEOUT_S)
    elapsed = time.monotonic() - started

    assert result.status == "execution_timeout", (
        f"expected the timeout status, got {result.status!r}"
    )
    assert elapsed < MUST_RETURN_BY, (
        f"the action blocked {elapsed:.3f}s against a {TIMEOUT_S}s "
        f"budget and a {SLEEP_S}s sleep; the timeout did not abort "
        "the action -- shutdown(wait=True) behind future.result() was "
        "waiting for the hung worker"
    )


def test_the_timeout_result_shape_is_unchanged(ex, monkeypatch):
    """The promptness fix must not change what callers see."""
    monkeypatch.setattr(
        ex, "_dispatch",
        lambda plan: (time.sleep(SLEEP_S)
                      or {"success": True, "executed": True}),
    )

    result = ex.execute(_plan(), timeout=TIMEOUT_S)

    assert result.status == "execution_timeout"
    assert result.error == "TimeoutError"
    assert result.executed is False
    assert result.metadata.get("execution_stage") == "dispatch"
    assert result.metadata.get("timeout_seconds") == TIMEOUT_S


# --------------------------------------------------------------------------
# The honest limit: the worker is abandoned, not killed
# --------------------------------------------------------------------------

def test_the_worker_is_abandoned_not_stopped(ex, monkeypatch):
    """What we CAN'T do, demonstrated rather than hidden.

    If the fix had somehow interrupted _dispatch, `finished` would be
    set when we check. It is not: the thread is still sleeping after
    the call has returned. That is the documented limitation.
    """
    finished = threading.Event()

    def _slow_dispatch(plan):
        time.sleep(0.8)
        finished.set()
        return {"success": True, "executed": True}

    monkeypatch.setattr(ex, "_dispatch", _slow_dispatch)

    result = ex.execute(_plan(), timeout=0.1)

    assert result.status == "execution_timeout"
    # The call has returned; the worker must NOT have been stopped
    # mid-flight (it cannot be) -- it is still out there.
    assert not finished.is_set(), (
        "the worker claims to have been stopped mid-call; a thread "
        "cannot be killed and this test exists so nobody pretends "
        "otherwise"
    )
    # ...and it does finish on its own shortly after.
    assert finished.wait(3.0), "the abandoned worker never finished"


def test_the_source_says_abandoned_rather_than_stopped():
    """Never claim a timeout was enforced harder than it was.

    The wording must live in the docstring (or code), not a comment:
    this test reads the function via AST and ast.unparse drops comments.
    """
    body = ast.unparse(_function_body("execute"))
    assert "abandoned" in body.lower(), (
        "the code does not document that a timed-out worker is "
        "abandoned rather than killed"
    )
    assert "cancel_futures=True" in body, (
        "the timeout path must shut the executor down without waiting"
    )


# --------------------------------------------------------------------------
# The success path still joins its worker (the trap in the fix itself)
# --------------------------------------------------------------------------

class _SpyExecutor(ThreadPoolExecutor):
    """Records shutdown() calls so the tests can see which path ran."""

    last = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shutdown_calls = []
        _SpyExecutor.last = self

    def shutdown(self, wait=True, **kwargs):
        self.shutdown_calls.append({"wait": wait, **kwargs})
        super().shutdown(wait=wait, **kwargs)


def _patch_executor(monkeypatch):
    # `execute` references the stdlib module attribute directly
    # (`import concurrent.futures`), so that is what must be patched;
    # monkeypatch restores it after the test.
    monkeypatch.setattr(
        "genesis_os.action_executor.concurrent.futures.ThreadPoolExecutor",
        _SpyExecutor,
    )


def test_a_successful_dispatch_still_joins_its_worker(ex, monkeypatch):
    """Regression for the fix's own trap.

    shutdown(wait=True) on the success path must survive: if the fix
    drops it, one worker thread leaks per healthy dispatch.
    """
    _patch_executor(monkeypatch)
    monkeypatch.setattr(
        ex, "_dispatch", lambda plan: {"success": True, "executed": True},
    )

    result = ex.execute(_plan(), timeout=5.0)

    assert result.status != "execution_timeout", (
        f"a healthy dispatch timed out: {result.status}"
    )
    calls = _SpyExecutor.last.shutdown_calls
    assert calls, "the executor was never shut down on the success path"
    assert any(c["wait"] is True for c in calls), (
        f"success path did not join its worker: {calls}"
    )


def test_the_timeout_path_shuts_down_without_waiting(ex, monkeypatch):
    _patch_executor(monkeypatch)
    monkeypatch.setattr(
        ex, "_dispatch",
        lambda plan: (time.sleep(SLEEP_S)
                      or {"success": True, "executed": True}),
    )

    result = ex.execute(_plan(), timeout=TIMEOUT_S)

    assert result.status == "execution_timeout"
    calls = _SpyExecutor.last.shutdown_calls
    assert calls, "the executor was never shut down on the timeout path"
    waited = [c["wait"] for c in calls]
    assert any(w is False for w in waited), (
        f"the timeout path waited for the hung worker: {calls}"
    )
    assert any(c.get("cancel_futures") for c in calls), (
        f"the timeout path did not cancel pending futures: {calls}"
    )


# --------------------------------------------------------------------------
# An exception stays an exception -- and does not become a block either
# --------------------------------------------------------------------------

def test_a_dispatch_exception_becomes_an_execution_exception(ex, monkeypatch):
    monkeypatch.setattr(
        ex, "_dispatch",
        lambda plan: (_ for _ in ()).throw(ValueError("boom")),
    )

    started = time.monotonic()
    result = ex.execute(_plan(), timeout=5.0)
    elapsed = time.monotonic() - started

    assert result.status == "execution_exception", (
        f"expected execution_exception, got {result.status!r}"
    )
    assert elapsed < 1.0, (
        f"an exception took {elapsed:.3f}s to surface -- the worker "
        "was joined behind it"
    )


def test_the_exception_path_shuts_down_without_waiting(ex, monkeypatch):
    _patch_executor(monkeypatch)
    monkeypatch.setattr(
        ex, "_dispatch",
        lambda plan: (_ for _ in ()).throw(ValueError("boom")),
    )

    result = ex.execute(_plan(), timeout=5.0)

    assert result.status == "execution_exception"
    calls = _SpyExecutor.last.shutdown_calls
    assert calls, "the executor was never shut down on the exception path"
    assert any(w is False for w in (c["wait"] for c in calls)), (
        f"the exception path waited for the worker: {calls}"
    )
    assert any(c.get("cancel_futures") for c in calls), (
        f"the exception path did not cancel pending futures: {calls}"
    )


# --------------------------------------------------------------------------
# Structural: the unenforceable `with` form is gone
# --------------------------------------------------------------------------

def test_the_blocking_with_form_is_gone():
    node = _function_body("execute")

    with_blocks = [n for n in ast.walk(node) if isinstance(n, ast.With)]
    offenders = []
    for block in with_blocks:
        for item in block.items:
            src = ast.unparse(item.context_expr)
            if "ThreadPoolExecutor" in src:
                offenders.append(src)

    assert not offenders, (
        f"`with ThreadPoolExecutor(...)` is back: {offenders}. The "
        "__exit__ runs shutdown(wait=True) and blocks behind the hung "
        "worker, so the per-action timeout cannot abort the call"
    )


def test_the_timeout_is_actually_passed_to_future_result():
    body = ast.unparse(_function_body("execute"))
    assert "_future.result(timeout=timeout)" in body, (
        "the timeout is no longer passed to future.result"
    )
