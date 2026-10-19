"""Item 17B (C15): the dispatch lock was held across the blocking call.

`_dispatch_with_fallback` wrapped its ENTIRE body in
`with self._dispatch_lock:` -- including `_dispatch_with_timeout(...)`,
the actual provider call, plus the Amendment-3 state-check callback and
the liveness probes. Everything behind that call blocks for its whole
duration: one slow operation therefore blocked every independent
operation on the same BrowserManager instance.

Reproduced against the committed original (two threads, one manager):

    fast latency: 0.844s (slow op had ~1.05s left to run)
    VERDICT     : BUG -- independent fast op blocked behind slow op

After the fix the same fast call completes while the slow one is still
running (~0.000s).

The fix NARROWS the lock instead of removing it:

  locked (fast, shared-state only):
    - provider-chain resolution (reads self._providers, lazy registry
      init in _get_registry),
    - session lookup/creation (mutates self._sessions),
    - the two registry health writes on timeout/failure, each wrapped
      individually.

  deliberately NOT locked, and why it is safe:
    - the provider call: driver mutual exclusion is the provider's own
      job, already done per method behind the provider's own lock
      (browser_playwright wraps every method in `with self._lock`;
      browser_selenium documents "every provider method is already
      serialised behind self._lock"),
    - _amendment3_gate: it runs the caller's state_check, user code
      that may itself block,
    - liveness probes: driver reads under the same provider lock.

Residual, stated honestly rather than hidden: two dispatches naming a
thread-SAFE provider can now run concurrently; thread-unsafe providers
were never protected by this lock anyway (their thread affinity
rejects a foreign thread whether or not the lock is held).
"""
from __future__ import annotations

import ast
import pathlib
import threading
import time
from types import SimpleNamespace

import pytest

from genesis_os.browser_manager import BrowserManager

MANAGER = pathlib.Path("genesis_os") / "browser_manager.py"

SLOW_SLEEP = 1.2
# Fail-before: the fast op waits out the remaining ~1.05s of the slow
# op (measured 0.844s with a 1.0s sleep). Pass-after: ~0.000s. Both
# sides sit well away from 0.6.
BLOCKED_THRESHOLD = 0.6


class _Provider:
    def __init__(self, name: str):
        self.name = name
        self.available = True


class _Entry:
    """Registry chain entry: the health fields the fix writes."""

    def __init__(self, name: str):
        self.provider_name = name
        self.last_health_check_result = None
        self.last_health_check_time = None


class _Registry:
    def __init__(self, entries):
        self._entries = list(entries)

    def is_idempotent(self, capability_id):
        # Idempotent => the gate allows fallback, so the dispatch walks
        # the whole chain and every failure path is reachable.
        return True

    def get_provider_chain(self, capability_id):
        return list(self._entries)


@pytest.fixture
def bm():
    # Skip the heavy __init__: only the dispatch lock, the provider
    # list and the session/registry accessors are needed.
    m = BrowserManager.__new__(BrowserManager)
    m._dispatch_lock = threading.Lock()
    m._providers = [_Provider("mock")]
    m._sessions = {}
    m._get_registry = lambda: None
    m._get_session = lambda sid="default": SimpleNamespace(
        provider=m._providers[0]
    )
    return m


def _function_body(name: str) -> ast.FunctionDef:
    tree = ast.parse(MANAGER.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {MANAGER}")


def _dispatch_lock_blocks() -> list[str]:
    """Unparsed source of every `with self._dispatch_lock` in the
    dispatch function."""
    fn = _function_body("_dispatch_with_fallback")
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.With):
            for item in node.items:
                if "self._dispatch_lock" in ast.unparse(item.context_expr):
                    out.append(ast.unparse(node))
                    break
    return out


# --------------------------------------------------------------------------
# The regression: an independent operation must not queue behind a
# slow one (reproduced at 0.844s before the fix)
# --------------------------------------------------------------------------

def test_an_independent_fast_op_is_not_blocked_by_a_slow_one(bm):
    results: dict = {}
    slow_started = threading.Event()

    def slow_op(p):
        slow_started.set()
        time.sleep(SLOW_SLEEP)
        return {"success": True, "op": "slow"}

    def fast_op(p):
        return {"success": True, "op": "fast"}

    def run(fn, key):
        results[key] = bm._dispatch_with_fallback("click", fn, timeout=10.0)

    t_slow = threading.Thread(target=run, args=(slow_op, "slow"))
    t_slow.start()
    assert slow_started.wait(3.0), "the slow op never started"
    time.sleep(0.15)  # the slow op is now inside the call itself

    started = time.monotonic()
    t_fast = threading.Thread(target=run, args=(fast_op, "fast"))
    t_fast.start()
    t_fast.join(5.0)
    latency = time.monotonic() - started
    t_slow.join(5.0)

    assert not t_fast.is_alive(), "the fast dispatch never returned"
    assert results.get("fast", {}).get("success") is True, results
    assert results.get("slow", {}).get("success") is True, results
    assert latency < BLOCKED_THRESHOLD, (
        f"the independent fast op took {latency:.3f}s while an "
        f"unrelated {SLOW_SLEEP}s op was still running; the dispatch "
        "lock is being held across the blocking provider call again"
    )


# --------------------------------------------------------------------------
# Structural: what the lock covers, and what it must not cover
# --------------------------------------------------------------------------

def test_the_provider_call_is_not_inside_the_lock():
    blocks = _dispatch_lock_blocks()
    assert blocks, "the dispatch lock block is gone entirely"
    offenders = [b for b in blocks if "_dispatch_with_timeout" in b]
    assert not offenders, (
        "the blocking provider call runs under self._dispatch_lock: "
        "one slow operation will again block every independent "
        "operation on the instance"
    )


def test_the_state_check_gate_is_not_inside_the_lock():
    """_amendment3_gate runs the CALLER's state_check -- user code
    that may block. It must not hold the dispatch lock while doing so.
    """
    blocks = _dispatch_lock_blocks()
    offenders = [b for b in blocks if "_amendment3_gate" in b]
    assert not offenders, (
        "the Amendment-3 gate (which runs the caller's state_check "
        "callback) is under the dispatch lock; a slow state check "
        "would block all dispatches"
    )


def test_resolution_and_session_lookup_still_happen_under_the_lock():
    """The lock was NARROWED, not deleted.

    Chain resolution (lazy registry init + self._providers iteration)
    and session creation (mutates self._sessions) are the shared state
    this lock exists to protect.
    """
    blocks = _dispatch_lock_blocks()
    resolution = [b for b in blocks if "_get_registry" in b]
    assert len(resolution) == 1, (
        f"expected exactly one locked resolution block, got "
        f"{len(resolution)} -- provider-chain resolution must stay "
        "under the dispatch lock"
    )
    src = resolution[0]
    assert "_get_session" in src, (
        "session lookup/creation (mutates self._sessions) is no "
        "longer under the dispatch lock"
    )
    assert "_dispatch_with_timeout" not in src
    assert "state_check" not in src, (
        "the caller's state_check callback leaked into the locked "
        "resolution block"
    )


def test_both_registry_health_writes_happen_under_the_lock():
    """A failed/timed-out provider must still be marked unhealthy on
    the registry -- but only inside a short locked section, not while
    the whole dispatch runs.
    """
    blocks = _dispatch_lock_blocks()
    health = [b for b in blocks if "last_health_check_result" in b]
    assert len(health) == 2, (
        f"expected 2 locked health-write blocks (timeout path + "
        f"exception path), got {len(health)}"
    )
    fn_src = ast.unparse(_function_body("_dispatch_with_fallback"))
    total = fn_src.count("last_health_check_result = False")
    locked = sum(b.count("last_health_check_result = False") for b in health)
    assert total == 2 and locked == total, (
        f"{total - locked} health write(s) run outside the dispatch "
        "lock; registry health state is shared and must be locked"
    )
    for b in health:
        assert "_dispatch_with_timeout" not in b, (
            "the blocking provider call ended up inside a health-write "
            "lock block"
        )


def test_the_docstring_documents_the_narrowed_scope():
    """Never let the comment claim a guarantee the code does not give
    -- or hide the one it dropped."""
    doc = ast.get_docstring(_function_body("_dispatch_with_fallback")) or ""
    assert "SHARED STATE ONLY" in doc, (
        "the docstring no longer states that the lock guards shared "
        "state only"
    )
    assert "browser_playwright" in doc and "self._lock" in doc, (
        "the docstring must point at the provider-level locks that "
        "actually protect driver access now"
    )
    assert "Residual, stated honestly" in doc, (
        "the residual concurrency (thread-safe providers may now run "
        "in parallel) is no longer stated honestly"
    )
    assert "state_check" in doc, (
        "the docstring no longer says the caller's state_check runs "
        "outside the lock"
    )
    raw = MANAGER.read_text(encoding="utf-8-sig")
    assert "ITEM 17B (C15): the critical section ends above" in raw, (
        "the end-of-critical-section marker comment is missing"
    )


# --------------------------------------------------------------------------
# Functional: narrowing the lock did not break what it protects
# --------------------------------------------------------------------------

def test_a_failing_provider_records_health_under_the_lock(bm):
    p1, p2 = _Provider("p1"), _Provider("p2")
    e1, e2 = _Entry("p1"), _Entry("p2")
    bm._providers[:] = [p1, p2]
    bm._get_registry = lambda: _Registry([e1, e2])

    def fn(p):
        if p.name == "p1":
            raise RuntimeError("boom")
        return {"success": True}

    result = bm._dispatch_with_fallback("click", fn, timeout=5.0)

    assert result["success"] is True, result
    assert result["_provider"] == "p2", "fallback to p2 did not happen"
    assert e1.last_health_check_result is False, (
        "the failing provider was not marked unhealthy on the registry"
    )
    assert isinstance(e1.last_health_check_time, float), (
        "the health write has no timestamp"
    )
    assert e2.last_health_check_result is None, (
        "a successful provider must not be marked unhealthy"
    )


def test_a_timed_out_provider_records_health_under_the_lock(bm):
    p1, p2 = _Provider("p1"), _Provider("p2")
    e1, e2 = _Entry("p1"), _Entry("p2")
    bm._providers[:] = [p1, p2]
    bm._get_registry = lambda: _Registry([e1, e2])

    def fn(p):
        if p.name == "p1":
            time.sleep(0.7)
        return {"success": True}

    started = time.monotonic()
    result = bm._dispatch_with_fallback("click", fn, timeout=0.15)
    elapsed = time.monotonic() - started

    assert result["success"] is True, result
    assert result["_provider"] == "p2", "fallback after timeout lost"
    assert elapsed < 0.9, (
        f"the timed-out provider stalled the dispatch for "
        f"{elapsed:.3f}s (the 17A abort is regressing)"
    )
    assert e1.last_health_check_result is False, (
        "the timed-out provider was not marked unhealthy on the "
        "registry"
    )
    assert e2.last_health_check_result is None
