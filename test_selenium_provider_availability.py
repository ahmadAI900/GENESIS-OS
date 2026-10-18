"""Item 15C (C13): a provider that could never start said it was available.

`SeleniumBrowserProvider._get_driver()` called

    webdriver.Chrome(service=..., options=..., service_timeout=60)

Selenium 4.48's signature is `(options, service, keep_alive)`. There is
no `service_timeout`, so EVERY call raised

    TypeError: WebDriver.__init__() got an unexpected keyword
               argument 'service_timeout'

before a browser was ever launched.

Two things made that invisible:

  * `_check_availability()` only imports selenium and looks for a
    chromedriver binary. Neither proves `webdriver.Chrome(...)` returns
    a driver, so the probe passed and the provider reported
    `available=True`.
  * every provider method wraps its body in try/except, so the TypeError
    became a generic "provider failed" result and never surfaced.

The provider was permanently non-functional and advertised itself as
healthy.

These tests inject a fake driver factory through `_create_driver`, so
the whole availability contract is exercised without Chrome being
installed, and without a network download.
"""
from __future__ import annotations

import inspect
import threading

import pytest

from genesis_os.browser_selenium import SeleniumBrowserProvider


# --------------------------------------------------------------------------
# The invalid kwarg
# --------------------------------------------------------------------------

def test_webdriver_chrome_rejects_service_timeout():
    """The premise. If Selenium ever accepts it, this item is moot."""
    selenium = pytest.importorskip("selenium")
    from selenium import webdriver

    params = inspect.signature(webdriver.Chrome.__init__).parameters
    assert "service_timeout" not in params, (
        "Selenium now accepts service_timeout; re-check whether the "
        "bounded driver creation is still needed"
    )


def test_the_provider_does_not_pass_service_timeout():
    """Structural guard against the exact kwarg reappearing.

    Checked against the AST, not the text: the item's own docstring
    has to be able to NAME `service_timeout` while explaining why it
    was removed, and a text search would either flag that explanation
    or be defeated by reformatting.
    """
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path("genesis_os") / "browser_selenium.py").read_text(
            encoding="utf-8-sig"
        )
    )

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "service_timeout"
    ]

    assert not offenders, (
        f"service_timeout is passed to a call at line(s) {offenders}; "
        "Selenium 4.x rejects it with TypeError on every driver creation"
    )


def test_the_bounded_call_passes_only_service_and_options():
    """And the real call shape is correct, not merely kwarg-free."""
    seen = {}

    class _FakeChrome:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    class _FakeService:
        def __init__(self, path):
            self.path = path

    class _FakeOptions:
        def add_argument(self, *_a):
            pass

    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    provider._driver = None
    provider.unavailable_reason = None
    provider._available = True
    provider.DRIVER_STARTUP_TIMEOUT_S = 5.0

    driver = provider._bounded_chrome_call(
        _FakeChrome, _FakeService, "C:/x/chromedriver.exe", _FakeOptions()
    )

    assert isinstance(driver, _FakeChrome)
    assert set(seen) == {"service", "options"}, (
        f"webdriver.Chrome was called with unexpected kwargs: {seen}"
    )


# --------------------------------------------------------------------------
# The availability contract
# --------------------------------------------------------------------------

def _provider_with(monkeypatch, driver_error=None):
    """A provider whose driver creation is fully injected.

    `Options` is patched through monkeypatch, NOT by assigning to the
    selenium module: an un-restored assignment would replace it for
    the rest of the process and quietly change every later test.
    """
    import selenium.webdriver.chrome.options as opts_mod

    class _FakeOptions:
        def add_argument(self, *_a):
            pass

    monkeypatch.setattr(opts_mod, "Options", _FakeOptions)

    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    provider._driver = None
    provider._lock = threading.RLock()
    provider.unavailable_reason = None
    provider._available = True
    provider._bounded_driver_download = lambda: "C:/x/chromedriver.exe"

    def _create(driver_path, options):
        if driver_error is not None:
            raise driver_error
        return FakeDriver()

    provider._create_driver = _create
    return provider


class FakeDriver:
    title = "https://example.test"

    def set_page_load_timeout(self, *_a):
        pass

    def set_script_timeout(self, *_a):
        pass

    def implicitly_wait(self, *_a):
        pass

    def quit(self):
        pass


def test_availability_is_not_claimed_when_creation_fails(monkeypatch):
    """The regression.

    The probe passed (selenium imports, chromedriver exists) and the
    provider said `available=True`. Creation then failed. Before this
    item nothing recorded that, so the provider kept claiming to be
    usable while every call raised.
    """
    provider = _provider_with(monkeypatch, TypeError("unexpected keyword argument"))

    assert provider.available is True, (
        "precondition: the provider starts out advertising itself"
    )

    with pytest.raises(TypeError):
        provider._ensure_driver()

    assert provider.available is False, (
        "driver creation failed and the provider STILL reports "
        "available=True; it is advertising a capability it does not have"
    )


def test_the_failure_reason_is_surfaced(monkeypatch):
    """Honest, not just a flipped boolean."""
    provider = _provider_with(monkeypatch, TypeError("unexpected keyword argument"))

    with pytest.raises(TypeError):
        provider._ensure_driver()

    assert provider.unavailable_reason, (
        "the provider went unavailable without saying why"
    )
    assert "driver creation failed" in provider.unavailable_reason
    assert "unexpected keyword argument" in provider.unavailable_reason


def test_a_timeout_at_creation_also_marks_unavailable(monkeypatch):
    provider = _provider_with(monkeypatch)
    provider._create_driver = lambda p, o: (_ for _ in ()).throw(
        TimeoutError("webdriver.Chrome did not return within 60s")
    )

    with pytest.raises(TimeoutError):
        provider._ensure_driver()

    assert provider.available is False, (
        "a driver that never came up was still advertised as available"
    )
    assert "did not return within" in (provider.unavailable_reason or "")


def test_a_hanging_creation_is_bounded_not_hung():
    """The wall clock has to be real.

    Exercised at the layer that owns the bound. Replacing `_create_driver`
    wholesale would BYPASS the bound, which is why this calls
    `_bounded_chrome_call` directly with a factory that never returns.
    """
    import time

    class _FakeService:
        def __init__(self, path):
            self.path = path

    class _FakeOptions:
        pass

    def _hangs(**_kwargs):
        threading.Event().wait(120)

    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    provider._driver = None
    provider.unavailable_reason = None
    provider._available = True
    provider.DRIVER_STARTUP_TIMEOUT_S = 0.3

    started = time.time()
    with pytest.raises(TimeoutError):
        provider._bounded_chrome_call(
            _hangs, _FakeService, "C:/x/chromedriver.exe", _FakeOptions()
        )
    elapsed = time.time() - started

    assert elapsed < 8.0, (
        f"driver creation was not bounded; took {elapsed:.1f}s"
    )


def test_a_factory_returning_nothing_is_an_error():
    """A None driver is not a driver."""
    class _FakeService:
        def __init__(self, path):
            self.path = path

    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    provider._driver = None
    provider.unavailable_reason = None
    provider._available = True
    provider.DRIVER_STARTUP_TIMEOUT_S = 5.0

    with pytest.raises(RuntimeError):
        provider._bounded_chrome_call(
            lambda **_k: None, _FakeService, "C:/x/chromedriver.exe", object()
        )


def test_a_successful_creation_leaves_the_provider_available(monkeypatch):
    provider = _provider_with(monkeypatch)

    provider._ensure_driver()

    assert provider.available is True
    assert provider.unavailable_reason is None
    assert provider._driver is not None


def test_availability_survives_repeated_calls_once_created(monkeypatch):
    provider = _provider_with(monkeypatch)

    provider._ensure_driver()
    first = provider._driver
    provider._ensure_driver()

    assert provider._driver is first, "a live driver was recreated"
    assert provider.available is True


# --------------------------------------------------------------------------
# The provider must not swallow a permanent startup failure
# --------------------------------------------------------------------------

def test_open_url_does_not_report_success_when_the_driver_cannot_start(monkeypatch):
    """End to end: the user-visible result, not the internal flag.

    `open_url` re-raises when there is no live driver rather than
    returning a dict -- deliberately, so the manager's
    `_dispatch_with_fallback` can fall through to the next provider.
    What matters here is that it does NOT report success, and that the
    provider stops claiming availability on the way out.
    """
    provider = _provider_with(
        monkeypatch, TypeError("unexpected keyword argument")
    )

    with pytest.raises(TypeError):
        provider.open_url("https://example.test")

    assert provider.available is False, (
        "a call that could not start a driver left the provider "
        "advertising available=True"
    )


def test_open_url_never_returns_success_without_a_driver(monkeypatch):
    """Whichever way the failure is surfaced, it is never a success."""
    provider = _provider_with(
        monkeypatch, TypeError("service_timeout was rejected")
    )

    try:
        result = provider.open_url("https://example.test")
    except Exception as exc:
        # Re-raised for the manager's fallback: fine, and the reason
        # survives intact.
        assert "service_timeout" in str(exc), (
            f"the real failure was replaced by a generic one: {exc}"
        )
    else:
        assert result.get("success") is not True, (
            f"open_url reported success with no driver: {result}"
        )

    assert provider.unavailable_reason, (
        "the provider failed without recording why"
    )
    assert "service_timeout" in provider.unavailable_reason, (
        f"the underlying error is not surfaced: {provider.unavailable_reason}"
    )


# --------------------------------------------------------------------------
# Structural guards
# --------------------------------------------------------------------------

def test_creation_goes_through_the_bounded_call():
    """The real _create_driver must delegate to the bounded path."""
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path("genesis_os") / "browser_selenium.py").read_text(
            encoding="utf-8-sig"
        )
    )

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_create_driver"
    )

    delegates = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_bounded_chrome_call"
    ]

    assert delegates, (
        "_create_driver no longer delegates to _bounded_chrome_call, so "
        "driver creation can escape the startup timeout"
    )


def test_creation_is_bounded_by_a_thread_and_a_join():
    source = inspect.getsource(SeleniumBrowserProvider._bounded_chrome_call)

    assert "threading.Thread" in source
    assert ".join(" in source
    assert "DRIVER_STARTUP_TIMEOUT_S" in source


def test_the_probe_result_is_not_treated_as_proof_of_startup():
    """Document the necessary/sufficient distinction structurally."""
    source = inspect.getsource(SeleniumBrowserProvider._ensure_driver)

    assert "_mark_unavailable" in source, (
        "_ensure_driver no longer records a startup failure, so a "
        "provider that cannot start keeps advertising availability"
    )


def test_available_property_reflects_the_marked_state():
    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    provider._available = True
    provider.unavailable_reason = None

    assert provider.available is True

    provider._mark_unavailable("driver creation failed: boom")

    assert provider.available is False
    assert "boom" in provider.unavailable_reason


def test_an_unavailable_provider_carries_a_reason():
    """Never a bare False with nothing to go on."""
    import genesis_os.browser_selenium as mod

    original = mod._probe_cache
    mod._probe_cache = 0
    mod._probe_cache_kind = "definitive"
    mod._probe_cache_at = 1e18
    try:
        provider = SeleniumBrowserProvider()
        assert provider.available is False
        assert provider.unavailable_reason, (
            "an unavailable provider gave no reason"
        )
    finally:
        mod._probe_cache = original
        mod._probe_cache_kind = ""
        mod._probe_cache_at = 0.0