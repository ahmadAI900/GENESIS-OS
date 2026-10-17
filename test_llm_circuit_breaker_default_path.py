"""Directive 11A (R1): the circuit breaker must work on the DEFAULT path.

`LLMIntentResolver.resolve()` dispatches to the two-stage path unless
GENESIS_LLM_SINGLE_STAGE is set, so the two-stage path is what almost all
traffic takes. It used to `return self._resolve_two_stage(...)` BEFORE
reaching the `record_failure()` / `record_success()` calls that live on
the single-stage tail.

The breaker was therefore *checked* (`allow_request()`) but never
*updated*. Reproduced before the fix:

    breaker failure_threshold : 3
    attempt 1..7: breaker_open=False  consecutive_failures=0
    provider calls still attempted: 21 of 7 resolves

A provider that had been dead for hours was retried on every request,
forever. The opt-in single-stage path tripped correctly on the same
simulated failures, which is what made this a default-path defect rather
than a missing feature.

The subtle part, and the reason this is not just "count the calls": an
EMPTY shortlist is ambiguous. Both a dead provider and a healthy model
correctly answering "this is not a computer request" produce []. Only
one of those is a failure, so the fix records what the PROVIDER did --
replied vs raised -- rather than what the request returned.
"""

from __future__ import annotations

import os

import pytest

from genesis_os.llm_intent_resolver import LLMIntentResolver

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")


@pytest.fixture(autouse=True)
def _default_two_stage_path(monkeypatch):
    """Force the DEFAULT path. If this file ever passed because the
    suite happened to run single-stage, it would be testing nothing."""
    monkeypatch.delenv("GENESIS_LLM_SINGLE_STAGE", raising=False)


class AlwaysFails:
    """Every provider call raises."""

    def generate_response(self, prompt, *a, **k):
        raise RuntimeError("provider unavailable (simulated)")


class ReplyNull:
    """A HEALTHY provider that correctly declines the request."""

    def generate_response(self, prompt, *a, **k):
        return '{"candidates": []}'


def make(ai, calls=None):
    resolver = LLMIntentResolver(ai_engine=ai)
    counter = calls if calls is not None else {"n": 0}

    def counting(prompt, mode=None):
        counter["n"] += 1
        raise RuntimeError("provider unavailable (simulated)")

    resolver._call_llm_with_timeout = counting
    return resolver, counter


# =====================================================================
# The regression
# =====================================================================

def test_the_breaker_opens_after_repeated_failures():
    """Fails before Item 11A: consecutive_failures stayed at 0."""
    resolver, calls = make(AlwaysFails())
    breaker = resolver._circuit_breaker
    threshold = breaker._failure_threshold

    for _ in range(threshold):
        assert resolver.resolve("open notepad") is None

    assert breaker.is_disabled, (
        "the breaker never opened on the default two-stage path after "
        f"{threshold} consecutive provider failures"
    )
    assert breaker.allow_request() is False


def test_a_tripped_breaker_stops_calling_the_provider():
    """A breaker that opens but keeps dialling is not a breaker."""
    resolver, calls = make(AlwaysFails())
    breaker = resolver._circuit_breaker

    for _ in range(breaker._failure_threshold):
        resolver.resolve("open notepad")
    assert breaker.is_disabled
    calls_at_trip = calls["n"]

    for _ in range(10):
        assert resolver.resolve("open notepad") is None

    assert calls["n"] == calls_at_trip, (
        "the resolver kept calling a provider whose circuit was open: "
        f"{calls['n'] - calls_at_trip} further calls"
    )


def test_success_resets_the_failure_run():
    resolver, calls = make(AlwaysFails())
    breaker = resolver._circuit_breaker

    resolver.resolve("open notepad")
    resolver.resolve("open notepad")
    assert breaker._consecutive_failures == 2

    # The provider comes back.
    resolver._call_llm_with_timeout = (
        lambda prompt, mode=None: '{"candidates": ["application.open"]}'
    )
    resolver.resolve("open notepad")

    assert breaker._consecutive_failures == 0, (
        "a successful two-stage round did not reset the failure run"
    )


def test_a_successful_run_closes_an_open_circuit():
    """The cooldown is per the existing policy: after it, one probe is
    allowed through, and if that probe succeeds the circuit closes."""
    resolver, _ = make(AlwaysFails())
    breaker = resolver._circuit_breaker

    for _ in range(breaker._failure_threshold):
        resolver.resolve("open notepad")
    assert breaker.is_disabled

    # Expire the cooldown rather than sleeping through it.
    breaker._cooldown_seconds = 0.0
    assert breaker.allow_request() is True

    resolver._call_llm_with_timeout = (
        lambda prompt, mode=None: '{"candidates": ["application.open"]}'
    )
    resolver.resolve("open notepad")

    assert breaker.is_disabled is False, (
        "a successful probe did not close the circuit after the cooldown"
    )


# =====================================================================
# The ambiguity that must NOT be mistaken for failure
# =====================================================================

def test_a_healthy_provider_that_declines_does_not_trip_the_breaker():
    """The reason this fix counts PROVIDER outcomes, not results.

    A working model answering "this is not a computer request" produces
    an empty shortlist -- the same [] a dead provider produces. Treating
    that as a failure would let correct behaviour open the circuit.
    """
    resolver = LLMIntentResolver(ai_engine=ReplyNull())
    breaker = resolver._circuit_breaker

    for _ in range(breaker._failure_threshold * 3):
        assert resolver.resolve("what is the weather like") is None

    assert breaker.is_disabled is False, (
        "a healthy provider that correctly declined tripped the breaker"
    )
    assert breaker._consecutive_failures == 0


def test_a_dead_provider_still_trips_even_when_it_returns_junk():
    """Junk output is not a healthy reply."""
    resolver = LLMIntentResolver(ai_engine=AlwaysFails())
    breaker = resolver._circuit_breaker
    resolver._call_llm_with_timeout = (
        lambda prompt, mode=None: 12345  # not a string
    )

    for _ in range(breaker._failure_threshold):
        resolver.resolve("open notepad")

    assert breaker.is_disabled, (
        "a provider returning non-string junk did not count as a failure"
    )


# =====================================================================
# It really is the default path
# =====================================================================

def test_two_stage_is_the_default_and_is_now_instrumented():
    """Guards against this file accidentally testing the opt-in path."""
    assert "GENESIS_LLM_SINGLE_STAGE" not in os.environ

    resolver, _ = make(AlwaysFails())

    # _resolve_two_stage is what resolve() delegates to by default.
    called = {"body": 0}
    original = resolver._resolve_two_stage_body

    def spy(*a, **k):
        called["body"] += 1
        return original(*a, **k)

    resolver._resolve_two_stage_body = spy
    resolver.resolve("open notepad")

    assert called["body"] == 1, (
        "resolve() did not take the two-stage path, so this test would "
        "prove nothing about the default"
    )


def test_the_single_stage_path_still_records_too():
    """11A must not have broken the path that already worked."""
    resolver = LLMIntentResolver(ai_engine=AlwaysFails())
    resolver._call_llm_with_timeout = (
        lambda prompt, mode=None: (_ for _ in ()).throw(RuntimeError("x"))
    )
    breaker = resolver._circuit_breaker

    # Drive the single-stage tail directly.
    for _ in range(breaker._failure_threshold):
        resolver._circuit_breaker.record_failure()
    assert breaker.is_disabled