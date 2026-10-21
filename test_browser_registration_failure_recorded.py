"""Item 25C (C20): provider registration swallowed every error, so
dead == absent.

``_try_register_selenium`` and ``_try_register_playwright`` each ended
in

    except ImportError: pass
    except Exception: pass

and recorded NOTHING. A provider whose registration CRASHED (constructor
raised, ``available`` blew up) simply disappeared from ``provider_names``
-- byte-for-byte identical to a machine where the library was never
installed. The constructor's own broad catch around the parallel probe
path was equally silent: it ran a sequential fallback and recorded no
trace that the parallel path had failed at all.

The fix classifies and records every outcome:

  - ImportError from the provider import -> absent (reason recorded),
  - provider.available is False           -> absent (reason recorded),
  - ANY other exception                   -> failed  (reason recorded),
  - parallel probe path exception        -> probe_path_failure set.

Exposed as ``provider_failures`` (crashed, with reason),
``provider_absences`` (genuinely not installed/unavailable, with
reason) and ``probe_path_failure``. "Absent" and "failed" are now
different dictionaries: a crash can no longer masquerade as absence.
"""
from __future__ import annotations

import threading

import pytest

from genesis_os.browser_manager import BrowserManager


class _UnavailableProvider:
    """Fast stand-in: installed but not usable (honest absent)."""

    name = "never"

    def __init__(self):
        self.available = False


class _ExplodingProvider:
    """Registration crashes AFTER the module imported cleanly."""

    name = "boom"

    def __init__(self):
        raise RuntimeError("simulated crash inside provider constructor")


def _patch_selenium(monkeypatch, provider_class):
    import genesis_os.browser_selenium as module

    monkeypatch.setattr(module, "SeleniumBrowserProvider", provider_class)


def _patch_playwright(monkeypatch, provider_class):
    import genesis_os.browser_playwright as module

    monkeypatch.setattr(module, "PlaywrightBrowserProvider", provider_class)


def test_crashing_provider_is_recorded_as_failed_not_absent(monkeypatch):
    _patch_selenium(monkeypatch, _ExplodingProvider)
    _patch_playwright(monkeypatch, _UnavailableProvider)

    manager = BrowserManager()

    failures = manager.provider_failures
    absences = manager.provider_absences

    assert "selenium" in failures, (
        "a crashing registration was recorded as nothing at all: the "
        f"provider simply vanished (failures={failures})"
    )
    assert "RuntimeError" in failures["selenium"], failures
    assert "simulated crash" in failures["selenium"], failures
    assert "selenium" not in absences, (
        "a crash must not be filed under absent: "
        f"absences={absences}"
    )
    assert "selenium" not in manager.provider_names

    # available-False is the honest ABSENT, and it stays distinct.
    assert "playwright" in absences, absences
    assert "playwright" not in failures, failures
    assert "playwright" not in manager.provider_names

    assert "webbrowser" in manager.provider_names
    # The crashed probe FINISHED (fast) -- this is a recorded failure,
    # not a probe-timeout degradation.
    assert manager.degraded is False
    assert manager.degraded_reason is None


def test_import_error_is_recorded_as_absent_with_reason(monkeypatch):
    import genesis_os.browser_playwright as playwright_module

    # Deleting the name makes `from ... import PlaywrightBrowserProvider`
    # raise ImportError -- the not-installed case.
    monkeypatch.delattr(playwright_module, "PlaywrightBrowserProvider")
    _patch_selenium(monkeypatch, _UnavailableProvider)

    manager = BrowserManager()

    absences = manager.provider_absences
    assert "playwright" in absences, absences
    assert "ImportError" in absences["playwright"], absences
    assert "playwright" not in manager.provider_failures, (
        "a missing import is absence, not failure"
    )
    assert "selenium" in absences, absences
    assert "webbrowser" in manager.provider_names


def test_parallel_probe_path_failure_is_recorded(monkeypatch):
    real_thread = threading.Thread

    def _exploding_thread(*args, **kwargs):
        if str(kwargs.get("name", "")).startswith("browser_probe"):
            raise RuntimeError("simulated thread creation failure")
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", _exploding_thread)
    _patch_selenium(monkeypatch, _UnavailableProvider)
    _patch_playwright(monkeypatch, _UnavailableProvider)

    manager = BrowserManager()

    note = manager.probe_path_failure
    assert note is not None, (
        "the parallel probe path failed and the catch recorded nothing"
    )
    assert "simulated thread creation failure" in note, note
    assert "sequential fallback used" in note, note

    # The sequential fallback still ran and each provider recorded
    # its own honest outcome.
    assert "selenium" in manager.provider_absences
    assert "playwright" in manager.provider_absences
    assert manager.provider_failures == {}
    assert "webbrowser" in manager.provider_names
    assert manager.degraded is False
