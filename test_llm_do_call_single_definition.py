"""Directive 12A (R3): exactly one _do_call, and it is the correct one.

`_call_llm_with_timeout` defined `_do_call` twice:

    line 2656  def _do_call():        # two bare returns, NO try/finally
    line 2696  def _do_call():        # try/except/finally: _release()

Python rebinds the name, so the second won and the first never ran.

The dead copy was not merely redundant, it was DANGEROUS. The live one
wraps the provider call in `try: ... finally: _release()`, which is what
returns the in-flight slot when the provider raises or the call is
abandoned on timeout. The dead copy has no `finally`, so anyone who
"fixed" the duplication by deleting the second definition -- the
obvious reading of "there are two, keep one" -- would silently convert
every provider failure into a leaked slot. That matters because
`_MAX_INFLIGHT_CALLS` bounds the live calls precisely because unjoined
workers pile up and saturate the provider.

Verified at runtime before the fix: with a raising provider,
`_inflight_calls` returned to 0, proving the try/finally definition was
the one executing.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
RESOLVER_SRC = BACKEND / "genesis_os" / "llm_intent_resolver.py"


def _call_timeout_node(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_call_llm_with_timeout"
        ):
            return node
    raise AssertionError("_call_llm_with_timeout not found")


def _do_call_defs():
    tree = ast.parse(RESOLVER_SRC.read_text(encoding="utf-8-sig"))
    fn = _call_timeout_node(tree)
    return [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.FunctionDef) and n.name == "_do_call"
    ]


# =====================================================================
# Structural
# =====================================================================

def test_there_is_exactly_one_do_call_definition():
    """The regression. Fails before Item 12A: there were two."""
    defs = _do_call_defs()
    assert len(defs) == 1, (
        f"_call_llm_with_timeout defines _do_call {len(defs)} times at "
        f"lines {[d.lineno for d in defs]}; the first is shadowed dead code"
    )


def test_the_module_defines_no_other_do_call_either():
    """Module-wide, not just in this one function."""
    tree = ast.parse(RESOLVER_SRC.read_text(encoding="utf-8-sig"))
    everywhere = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_do_call"
    ]
    assert len(everywhere) == 1, (
        f"_do_call is defined {len(everywhere)} times module-wide at "
        f"{everywhere}"
    )


def test_the_surviving_definition_releases_the_inflight_slot():
    """It must be the try/finally one, not the bare-return one.

    This is the assertion that makes the deletion safe rather than
    arbitrary: if a future edit keeps the wrong copy, the provider slot
    leaks on every failure and the cap starts rejecting healthy calls.
    """
    (only,) = _do_call_defs()
    has_finally = any(
        isinstance(stmt, ast.Try) and stmt.finalbody for stmt in only.body
    )
    assert has_finally, (
        "the surviving _do_call has no try/finally, so _release() would "
        "not run when the provider raises -- that is the DEAD copy that "
        "was kept before Item 12A"
    )


def test_release_is_still_defined_before_do_call_runs():
    """Ordering matters: the live def closes over _release."""
    tree = ast.parse(RESOLVER_SRC.read_text(encoding="utf-8-sig"))
    fn = _call_timeout_node(tree)
    names = {
        n.name for n in fn.body if isinstance(n, ast.FunctionDef)
    }
    assert "_release" in names, sorted(names)


# =====================================================================
# Behavioural: the slot is released
# =====================================================================

class BoomEngine:
    def generate_response(self, prompt, *a, **k):
        raise RuntimeError("provider exploded")


class OkEngine:
    def generate_response(self, prompt, *a, **k):
        return "ok"


def test_a_raising_provider_still_releases_its_slot():
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    resolver = LLMIntentResolver(ai_engine=BoomEngine())
    before = getattr(resolver, "_inflight_calls", None)

    with pytest.raises(RuntimeError):
        resolver._call_llm_with_timeout("hello")

    after = getattr(resolver, "_inflight_calls", None)
    assert after == before, (
        f"in-flight slot leaked: {before} -> {after}. The surviving "
        f"_do_call must keep its finally: _release()."
    )


def test_a_successful_call_still_releases_its_slot():
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    resolver = LLMIntentResolver(ai_engine=OkEngine())
    before = getattr(resolver, "_inflight_calls", None)

    assert resolver._call_llm_with_timeout("hello") == "ok"

    after = getattr(resolver, "_inflight_calls", None)
    assert after == before, f"slot leaked on success: {before} -> {after}"


def test_repeated_failures_do_not_exhaust_the_slot_budget():
    """The real consequence of a missing finally: after N failures the
    cap is consumed and every later call is refused."""
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    resolver = LLMIntentResolver(ai_engine=BoomEngine())

    # Far more failures than the cap allows. If any slot leaked, the
    # budget would be exhausted and this would raise the budget error
    # rather than the provider error.
    for _ in range(20):
        with pytest.raises(RuntimeError):
            resolver._call_llm_with_timeout("hello")

    assert getattr(resolver, "_inflight_calls", None) == 0, (
        "slots accumulated across failures; the finally clause is gone"
    )


def test_the_call_timeout_path_is_unaffected():
    """The method still enforces its timeout through the live closure."""
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    class Hanging:
        def generate_response(self, prompt, *a, **k):
            import time

            time.sleep(30)
            return "never"

    resolver = LLMIntentResolver(ai_engine=Hanging())
    original = resolver._LLM_CALL_TIMEOUT
    resolver._LLM_CALL_TIMEOUT = 0.2
    try:
        from concurrent.futures import TimeoutError as FuturesTimeoutError

        with pytest.raises(FuturesTimeoutError):
            resolver._call_llm_with_timeout("hello")
    finally:
        resolver._LLM_CALL_TIMEOUT = original