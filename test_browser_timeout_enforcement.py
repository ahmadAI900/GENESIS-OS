"""Directive 13B (C5): browser timeouts that are real, and honest about it.

THREE defects, none of which could interrupt anything:

1. A TIMEOUT CHECK THAT COULD NEVER FIRE. In
   `BrowserManager._dispatch_with_timeout`, the thread-unsafe branch ran

       start = time.monotonic()
       ...
       if time.monotonic() - start > timeout:
           raise FuturesTimeoutError(timeout)
       result = fn()

   The check ran BEFORE `fn()`, so `start` was microseconds old and the
   condition was never true. It read like a hard timeout and enforced
   nothing. A hanging Playwright or Selenium call blocked forever.

2. AN OVERRUN REPORTED AS SUCCESS. When a call did return after missing
   its deadline, the manager set `_timeout_overrun` and handed the result
   back unchanged. Reproduced: a call taking 0.313s against a 0.05s cap
   came back with `success=True`. Any caller trusting `success` saw a
   green result for an operation that blew its budget ~6x.

3. NO TIMEOUT ANYWHERE AT THE DRIVER. Nothing bounded the thing that
   actually blocks:

       selenium:  no set_page_load_timeout / set_script_timeout, and
                  ChromeDriverManager().install() -- a NETWORK DOWNLOAD
                  -- ran unbounded on driver creation.
       playwright: no set_default_timeout /
                  set_default_navigation_timeout, `launch()` with no
                  timeout, and two `page.goto(wait_until="networkidle")`
                  calls with no timeout. `networkidle` never settles on a
                  page holding a websocket or long-poll.

WHAT THIS FIX DOES, AND WHAT IT STILL CANNOT DO.

A hard kill is impossible for these providers: Playwright's sync API and
WebDriver are both bound to the thread that created them, which is
precisely why the manager dispatches them in-process. So:

  * the WALL CLOCK is bounded by the driver, which is the only layer
    that can actually give up -- real Playwright/WebDriver timeouts;
  * an overrun now FAILS the operation instead of being certified, with
    the honest `_timeout_overrun` flag retained as information.

This does not claim a hard timeout that does not exist. The overrun
path is a refusal to certify a result we know missed its deadline, not
an interruption.
"""

from __future__ import annotations

import ast
import pathlib
import time

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
MANAGER = BACKEND / "genesis_os" / "browser_manager.py"
SELENIUM = BACKEND / "genesis_os" / "browser_selenium.py"
PLAYWRIGHT = BACKEND / "genesis_os" / "browser_playwright.py"


def _manager():
    from genesis_os.browser_manager import BrowserManager

    return BrowserManager.__new__(BrowserManager)


# =====================================================================
# Defect 2: an overrun must not be reported as success
# =====================================================================

class _SlowProvider:
    """A thread-unsafe provider whose call overruns."""

    name = "playwright"

    @staticmethod
    def click(selector):
        time.sleep(0.30)
        return {"success": True, "clicked": selector}


def test_an_overrunning_call_is_reported_as_failure():
    """The regression. Fails before Item 13B: returned success=True."""
    manager = _manager()

    result = manager._dispatch_with_timeout(
        lambda: _SlowProvider.click("#btn"),
        0.05,
        provider_name="playwright",
    )

    assert result["success"] is False, (
        "a call that missed its deadline was reported as a success; "
        f"result={result}"
    )


def test_an_overrun_still_carries_the_honest_flag():
    """The flag is information, not a pass/fail channel."""
    manager = _manager()

    result = manager._dispatch_with_timeout(
        lambda: _SlowProvider.click("#btn"),
        0.05,
        provider_name="playwright",
    )

    assert result["_timeout_overrun"] is True, result
    assert result["_timeout_s"] == 0.05, result
    error = result.get("error", "")
    assert "budget" in error or "timeout" in error.lower(), result
    assert "FAILED" in error, (
        f"the error should say the operation was reported as failed: {error}"
    )


def test_an_overrun_is_never_marked_verified():
    manager = _manager()

    result = manager._dispatch_with_timeout(
        lambda: _SlowProvider.click("#btn"),
        0.05,
        provider_name="playwright",
    )

    assert result["verified"] is False, (
        f"a late result was marked verified: {result}"
    )


def test_a_call_inside_its_budget_is_untouched():
    """The fix must not fail honest work."""
    manager = _manager()

    result = manager._dispatch_with_timeout(
        lambda: {"success": True, "clicked": "#btn"},
        5.0,
        provider_name="playwright",
    )

    assert result["success"] is True, result
    assert "_timeout_overrun" not in result, result
    assert "error" not in result, result


# =====================================================================
# Defect 1: the check that could never fire is gone
# =====================================================================

def test_the_pre_call_deadline_check_is_gone():
    """It read like a hard timeout and enforced nothing."""
    source = MANAGER.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_dispatch_with_timeout"
        ):
            body = ast.unparse(node)
            assert "_time.monotonic() - start > timeout" not in body, (
                "the pre-call deadline check is back; it runs before "
                "fn() so the condition can never be true"
            )
            break
    else:
        raise AssertionError("_dispatch_with_timeout not found")


def test_the_documented_timeout_still_says_it_is_best_effort():
    """Never claim a timeout was enforced if it wasn't."""
    source = MANAGER.read_text(encoding="utf-8-sig")
    doc = ""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_dispatch_with_timeout"
        ):
            doc = ast.get_docstring(node) or ""
            break
    assert "no hard kill" in doc.lower() or "best-effort" in doc.lower(), (
        "the docstring must keep saying the timeout cannot be enforced "
        "on the calling thread"
    )


# =====================================================================
# Defect 3: real driver-level timeouts
# =====================================================================

def test_playwright_sets_real_driver_timeouts():
    from genesis_os.browser_playwright import PlaywrightBrowserProvider as P

    assert P.LAUNCH_TIMEOUT_MS > 0, "browser launch is unbounded"
    assert P.DEFAULT_TIMEOUT_MS > 0, "no default action timeout"
    assert P.NAVIGATION_TIMEOUT_MS > 0, "no default navigation timeout"

    source = PLAYWRIGHT.read_text(encoding="utf-8-sig")
    assert "set_default_timeout" in source, (
        "the context carries no default action timeout"
    )
    assert "set_default_navigation_timeout" in source, (
        "the context carries no default navigation timeout"
    )
    assert "timeout=self.LAUNCH_TIMEOUT_MS" in source, (
        "chromium.launch() is unbounded"
    )


def test_every_playwright_goto_is_bounded():
    """`wait_until="networkidle"` never settles on a page holding a
    websocket or long-poll, so an unbounded goto is an unbounded hang."""
    source = PLAYWRIGHT.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    unbounded = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "goto"
        ):
            if not any(kw.arg == "timeout" for kw in node.keywords):
                unbounded.append(node.lineno)

    assert not unbounded, (
        f"page.goto() without a timeout at lines {unbounded}; "
        f"networkidle can wait forever"
    )


def test_selenium_sets_real_driver_timeouts():
    from genesis_os.browser_selenium import SeleniumBrowserProvider as S

    assert S.PAGE_LOAD_TIMEOUT_S > 0, "page load is unbounded"
    assert S.SCRIPT_TIMEOUT_S > 0, "script execution is unbounded"
    assert S.DRIVER_STARTUP_TIMEOUT_S > 0, "driver startup is unbounded"
    assert S.DRIVER_DOWNLOAD_TIMEOUT_S > 0, (
        "the chromedriver DOWNLOAD is unbounded; it is network IO and is "
        "the easiest way to hang on a machine with no route out"
    )

    source = SELENIUM.read_text(encoding="utf-8-sig")
    assert "set_page_load_timeout" in source, source[:0] or None
    assert "set_script_timeout" in source
    assert "service_timeout=" in source, "driver startup is unbounded"


def test_the_driver_download_is_bounded_and_raises_on_timeout(monkeypatch):
    """A stalled download must surface as a failure, not a hang."""
    from genesis_os.browser_selenium import SeleniumBrowserProvider

    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    import threading
    import time as _time

    provider._driver = None
    provider._lock = threading.RLock()
    provider.DRIVER_DOWNLOAD_TIMEOUT_S = 0.2

    try:
        import webdriver_manager.chrome  # noqa: F401
    except Exception:
        pytest.skip("webdriver_manager not installed")

    def slow_install(self=None):
        _time.sleep(30)
        return "never"

    monkeypatch.setattr(
        "webdriver_manager.chrome.ChromeDriverManager.install",
        staticmethod(slow_install),
    )

    started = _time.monotonic()
    with pytest.raises(TimeoutError):
        provider._bounded_driver_download()
    elapsed = _time.monotonic() - started

    assert elapsed < 5.0, (
        f"the bounded download waited {elapsed:.1f}s; it is not bounded"
    )


# =====================================================================
# Structural
# =====================================================================

def test_no_unbounded_network_download_of_the_driver():
    """`ChromeDriverManager().install()` must not be called bare."""
    source = SELENIUM.read_text(encoding="utf-8-sig")
    assert "service=Service(ChromeDriverManager().install())" not in source, (
        "the driver download is still unbounded and inlined into the "
        "webdriver.Chrome(...) call"
    )
    assert "DRIVER_DOWNLOAD_TIMEOUT_S" in source, (
        "the bounded download helper is not used"
    )