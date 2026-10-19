"""Item 17A (C14): the per-dispatch timeout could not fire.

`_dispatch_with_timeout` ran:

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        return future.result(timeout=timeout)

future.result(timeout) DID raise FuturesTimeoutError on time, but
leaving the `with` block then ran ThreadPoolExecutor.__exit__ ->
shutdown(wait=True), which waits for the hung fn() to finish. The
timeout fired on paper and the caller still paid the whole overrun.

Measured against the committed original, a 1.2s sleep against a 0.25s
budget:

    outcome : TimeoutError raised (at 1.2s, not 0.25s)
    elapsed : 1.2s+  -- the timeout never aborted anything

The honest limit, stated rather than hidden: shutdown(wait=False)
does not kill the worker. A thread that cannot be interrupted is
ABANDONED -- still running until fn() returns on its own. This test
pins both sides: the CALL returns near the timeout, and the worker
really is still out there (we do not pretend it was stopped).

Mirrors the pattern already used in llm_intent_resolver.py and
browser_selenium.py's bounded driver download.
"""
from __future__ import annotations

import ast
import pathlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest

from genesis_os.browser_manager import BrowserManager

MANAGER = pathlib.Path("genesis_os") / "browser_manager.py"

SLEEP_S = 1.2
TIMEOUT_S = 0.25
# Fail-before ~1.2s; pass-after ~0.3s. Both sides sit far from 0.9.
MUST_RETURN_BY = 0.9


@pytest.fixture
def bm():
    # The method under test is stateless; skip the heavy __init__.
    return BrowserManager.__new__(BrowserManager)


def _function_body(name):
    tree = ast.parse(MANAGER.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {MANAGER}")


# --------------------------------------------------------------------------
# The regression: a slow call returns at ~timeout, not after the full sleep
# --------------------------------------------------------------------------

def test_a_hung_call_returns_near_the_timeout(bm):
    started = time.monotonic()

    with pytest.raises(FuturesTimeoutError):
        bm._dispatch_with_timeout(
            lambda: time.sleep(SLEEP_S), TIMEOUT_S, provider_name="mock"
        )

    elapsed = time.monotonic() - started
    assert elapsed < MUST_RETURN_BY, (
        f"the call blocked {elapsed:.3f}s against a {TIMEOUT_S}s "
        f"budget and a {SLEEP_S}s sleep; the timeout did not abort "
        "the call -- shutdown(wait=True) behind future.result() was "
        "waiting for the hung worker"
    )


def test_the_timeout_error_is_still_the_real_futures_timeout(bm):
    """The promptness fix must not change what callers catch."""
    with pytest.raises(FuturesTimeoutError):
        bm._dispatch_with_timeout(
            lambda: time.sleep(SLEEP_S), TIMEOUT_S, provider_name="mock"
        )


# --------------------------------------------------------------------------
# The honest limit: the worker is abandoned, not killed
# --------------------------------------------------------------------------

def test_the_worker_is_abandoned_not_stopped(bm):
    """What we CAN'T do, demonstrated rather than hidden.

    If the fix had somehow interrupted fn(), `finished` would be set
    when we check. It is not: the thread is still sleeping after the
    call has returned. That is the documented limitation.
    """
    finished = threading.Event()

    def _work():
        time.sleep(0.8)
        finished.set()

    with pytest.raises(FuturesTimeoutError):
        bm._dispatch_with_timeout(_work, 0.1, provider_name="mock")

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
    """Never claim a timeout was enforced harder than it was."""
    body = ast.unparse(_function_body("_dispatch_with_timeout"))
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


def test_a_successful_call_still_joins_its_worker(bm, monkeypatch):
    """Regression for the fix's own trap.

    `else: executor.shutdown(wait=True)` never runs when the `return`
    sits inside the `try` (Python skips `else` after a return --
    verified). That would leave one worker thread leaked per healthy
    dispatch. The return is deliberately outside the try; this test
    pins the shutdown call either way.
    """
    monkeypatch.setattr(
        "genesis_os.browser_manager.ThreadPoolExecutor", _SpyExecutor
    )

    result = bm._dispatch_with_timeout(
        lambda: {"success": True}, 5.0, provider_name="mock"
    )

    assert result == {"success": True}
    calls = _SpyExecutor.last.shutdown_calls
    assert calls, "the executor was never shut down on the success path"
    assert any(c["wait"] is True for c in calls), (
        f"success path did not join its worker: {calls}"
    )


def test_the_timeout_path_shuts_down_without_waiting(bm, monkeypatch):
    monkeypatch.setattr(
        "genesis_os.browser_manager.ThreadPoolExecutor", _SpyExecutor
    )

    with pytest.raises(FuturesTimeoutError):
        bm._dispatch_with_timeout(
            lambda: time.sleep(SLEEP_S), TIMEOUT_S, provider_name="mock"
        )

    calls = _SpyExecutor.last.shutdown_calls
    assert calls, "the executor was never shut down on the timeout path"
    waited = [c["wait"] for c in calls]
    assert any(w is False for w in waited), (
        f"the timeout path waited for the hung worker: {calls}"
    )
    assert any(c.get("cancel_futures") for c in calls), (
        f"the timeout path did not cancel pending futures: {calls}"
    )


def test_a_worker_exception_propagates_promptly(bm):
    """A raising fn must not turn into a block either."""
    started = time.monotonic()

    with pytest.raises(ValueError, match="boom"):
        bm._dispatch_with_timeout(
            lambda: (_ for _ in ()).throw(ValueError("boom")),
            5.0,
            provider_name="mock",
        )

    assert time.monotonic() - started < 1.0


# --------------------------------------------------------------------------
# Structural: the unenforceable `with` form is gone
# --------------------------------------------------------------------------

def test_the_blocking_with_form_is_gone():
    node = _function_body("_dispatch_with_timeout")

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
        "worker, so the timeout cannot abort the call"
    )


def test_the_timeout_is_actually_passed_to_future_result():
    node = _function_body("_dispatch_with_timeout")
    body = ast.unparse(node)
    assert "future.result(timeout=timeout)" in body, (
        "the timeout is no longer passed to future.result"
    )
