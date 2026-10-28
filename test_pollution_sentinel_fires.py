"""Prove the conftest pollution sentinel still fails a leaking test.

This is deliberately fast and non-live: it drives the sentinel fixture
directly instead of constructing a runtime, so the proof runs on every
fast gate. The sentinel is the only thing standing between a test that
mutates a process-global and every test that runs after it.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import conftest as backend_conftest


def test_pollution_sentinel_fails_a_watched_global_mutation():
    """A watched-global mutation must be reported by test name."""
    request = SimpleNamespace(node=SimpleNamespace(name="test_synthetic_leaker"))

    original = os.sep
    fixture = backend_conftest.pollution_sentinel.__wrapped__(request)
    next(fixture)
    try:
        os.sep = "/" if original != "/" else "\\"
        with pytest.raises(pytest.fail.Exception) as caught:
            next(fixture)
    finally:
        os.sep = original

    message = str(caught.value)
    assert "test_synthetic_leaker" in message, message
    assert "os.sep" in message, message
