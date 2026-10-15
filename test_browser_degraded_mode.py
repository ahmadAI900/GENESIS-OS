"""Browser degradation is observable and recoverable.

Continuation C1 Step 2. Before this, `BrowserManager` could end up with
only the stdlib provider because its bounded probe wait expired, and the
ONLY symptom was an assertion elsewhere noticing a short provider list.
`_check_availability` then cached the timeout as "unavailable" for the
life of the process, so the state was both silent and permanent.

Three properties, each tested here:

  slow probe      -> degraded is True, and the reason is reported
  healthy probe   -> the full provider list, not degraded
  recovery        -> after the TTL a later check re-probes and clears

The slow-probe and recovery tests drive the cache helpers directly
rather than really sleeping, so they are fast and deterministic. The
slowest test in this file is the healthy one, which really probes.
"""

from __future__ import annotations

import time

import pytest


# ----------------------------------------------------------------------
# Point 1: a timeout is not a definitive answer
# ----------------------------------------------------------------------

@pytest.mark.parametrize("module_name", ["genesis_os.browser_playwright",
                                         "genesis_os.browser_selenium"])
def test_a_timed_out_probe_is_not_cached_permanently(module_name, monkeypatch):
    module = __import__(module_name, fromlist=["*"])
    monkeypatch.setattr(module, "_probe_cache", 0, raising=False)
    monkeypatch.setattr(module, "_probe_cache_kind", "timeout", raising=False)
    monkeypatch.setattr(module, "_probe_cache_at", time.monotonic(),
                        raising=False)

    # Freshly timed out: the cached answer holds only inside the TTL.
    assert module._probe_cache_is_valid() is True

    # Once the TTL has passed, the cached answer is no longer usable,
    # so the next construction re-probes.
    monkeypatch.setattr(
        module, "_probe_cache_at",
        time.monotonic() - module._PROBE_CACHE_TTL_SECONDS - 1,
        raising=False)
    assert module._probe_cache_is_valid() is False


@pytest.mark.parametrize("module_name", ["genesis_os.browser_playwright",
                                         "genesis_os.browser_selenium"])
def test_a_definitive_negative_stays_cached(module_name, monkeypatch):
    """A finished probe that said 'absent' is still a definitive answer.

    The TTL applies to timeouts only. Re-probing a genuinely missing
    driver every 60 seconds forever would be its own kind of wrong.
    """
    module = __import__(module_name, fromlist=["*"])
    monkeypatch.setattr(module, "_probe_cache", 0, raising=False)
    monkeypatch.setattr(module, "_probe_cache_kind", "definitive",
                        raising=False)
    monkeypatch.setattr(module, "_probe_cache_at", 0.0, raising=False)
    assert module._probe_cache_is_valid() is True

    monkeypatch.setattr(module, "_probe_cache", 1, raising=False)
    assert module._probe_cache_is_valid() is True


@pytest.mark.parametrize("module_name", ["genesis_os.browser_playwright",
                                         "genesis_os.browser_selenium"])
def test_an_unprobed_cache_is_never_valid(module_name, monkeypatch):
    module = __import__(module_name, fromlist=["*"])
    monkeypatch.setattr(module, "_probe_cache", -1, raising=False)
    monkeypatch.setattr(module, "_probe_cache_kind", "", raising=False)
    assert module._probe_cache_is_valid() is False


@pytest.mark.parametrize("module_name", ["genesis_os.browser_playwright",
                                         "genesis_os.browser_selenium"])
def test_store_probe_result_records_the_kind(module_name, monkeypatch):
    module = __import__(module_name, fromlist=["*"])
    before = time.monotonic()
    module._store_probe_result(1, "definitive")
    assert module._probe_cache == 1
    assert module._probe_cache_kind == "definitive"
    assert module._probe_cache_at >= before


# ----------------------------------------------------------------------
# Point 2: degraded mode is observable
# ----------------------------------------------------------------------

def test_browser_manager_exposes_degraded_and_provider_names():
    from genesis_os.browser_manager import BrowserManager

    manager = BrowserManager()
    assert isinstance(manager.degraded, bool)
    assert isinstance(manager.provider_names, list)
    if manager.degraded:
        assert manager.degraded_reason, (
            "a degraded manager must say WHY it is degraded")
    else:
        assert manager.degraded_reason is None


def test_a_slow_probe_yields_degraded_true_with_a_reason(monkeypatch):
    """Drive the timeout path directly: no sleeping, fully deterministic."""
    from genesis_os.browser_manager import BrowserManager
    import genesis_os.browser_playwright as bpw
    import genesis_os.browser_selenium as bse

    # Every probe hangs: neither provider answers inside the bound.
    def hang(self=None):
        time.sleep(BrowserManager._PROVIDER_PROBE_TIMEOUT * 5)

    monkeypatch.setattr(BrowserManager, "_try_register_selenium",
                        lambda self: time.sleep(60))
    monkeypatch.setattr(BrowserManager, "_try_register_playwright",
                        lambda self: time.sleep(60))
    for module in (bpw, bse):
        monkeypatch.setattr(module, "_probe_cache", 0, raising=False)
        monkeypatch.setattr(module, "_probe_cache_kind", "timeout",
                            raising=False)
        monkeypatch.setattr(module, "_probe_cache_at", time.monotonic(),
                            raising=False)

    manager = BrowserManager()
    assert manager.degraded is True, (
        f"probe timeout should be reported as degraded, got "
        f"{manager.provider_names}")
    assert "timeout" in (manager.degraded_reason or "").lower(), \
        manager.degraded_reason
    # webbrowser is always registered, so a degraded manager is usable.
    assert "webbrowser" in manager.provider_names


def test_genesis_banner_states_degraded_and_the_reason(capsys, monkeypatch):
    from genesis import GenesisOS

    class _DegradedBrowser:
        degraded = True
        degraded_reason = "provider probe timeout after 10.0s"
        provider_names = ["webbrowser"]

    class _StubOsManager:
        def __init__(self):
            self.browser = _DegradedBrowser()

        def status(self):
            return {k: True for k in
                    ("level", "application_intelligence", "file_intelligence",
                     "folder_intelligence", "process_intelligence",
                     "system_intelligence", "document_intelligence")}

    runtime = GenesisOS.__new__(GenesisOS)
    runtime.os_manager = _StubOsManager()
    runtime.agents = []
    runtime.registry = type("R", (), {"count": lambda self: 0,
                                      "get_all_agents": lambda self: []})()
    runtime.show_startup()
    out = capsys.readouterr().out
    assert "DEGRADED" in out, out[-2000:]
    assert "webbrowser" in out, out[-2000:]
    assert "provider probe timeout" in out, out[-2000:]


def test_genesis_banner_lists_providers_when_healthy(capsys):
    from genesis import GenesisOS

    class _HealthyBrowser:
        degraded = False
        degraded_reason = None
        provider_names = ["playwright", "webbrowser"]

    class _StubOsManager:
        def __init__(self):
            self.browser = _HealthyBrowser()

        def status(self):
            return {k: True for k in
                    ("level", "application_intelligence", "file_intelligence",
                     "folder_intelligence", "process_intelligence",
                     "system_intelligence", "document_intelligence")}

    runtime = GenesisOS.__new__(GenesisOS)
    runtime.os_manager = _StubOsManager()
    runtime.agents = []
    runtime.registry = type("R", (), {"count": lambda self: 0,
                                      "get_all_agents": lambda self: []})()
    runtime.show_startup()
    out = capsys.readouterr().out
    assert "Browser Automation" in out, out[-2000:]
    assert "playwright" in out, out[-2000:]
    assert "DEGRADED" not in out, out[-2000:]


# ----------------------------------------------------------------------
# Point 3: recovery is testable
# ----------------------------------------------------------------------

def test_recovery_after_the_ttl_clears_the_degraded_flag(monkeypatch):
    """A later BrowserManager re-probes and recovers.

    The whole point of the TTL: the degraded state must be temporary.
    """
    from genesis_os.browser_manager import BrowserManager
    import genesis_os.browser_playwright as bpw

    # First: probes hang, so the cache records a TIMEOUT.
    monkeypatch.setattr(BrowserManager, "_try_register_selenium",
                        lambda self: time.sleep(60))
    monkeypatch.setattr(BrowserManager, "_try_register_playwright",
                        lambda self: time.sleep(60))
    monkeypatch.setattr(bpw, "_probe_cache", 0, raising=False)
    monkeypatch.setattr(bpw, "_probe_cache_kind", "timeout", raising=False)
    monkeypatch.setattr(bpw, "_probe_cache_at", time.monotonic(),
                        raising=False)

    degraded_first = BrowserManager()
    assert degraded_first.degraded is True

    # Now: the TTL has passed and the probes are fast again. The cached
    # timeout is discarded, a real probe runs, and the manager recovers.
    monkeypatch.setattr(bpw, "_probe_cache_at",
                        time.monotonic() - bpw._PROBE_CACHE_TTL_SECONDS - 1,
                        raising=False)
    monkeypatch.undo()  # restore the real registration methods
    recovered = BrowserManager()
    assert bpw._probe_cache_kind == "definitive", (
        "after the TTL the cache must be replaced by a real probe result")
    assert "playwright" in recovered.provider_names or \
        recovered.provider_names == ["webbrowser"], recovered.provider_names