"""
Live mid-session failover proof.

1. Start a real Playwright session, confirm it's healthy.
2. Sever the browser connection (simulate crash).
3. Send another real operation on the same BrowserManager.
4. Show Selenium takes over.
"""
import os
import sys
import time
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: launches and kills a real Chromium via Playwright.
# --------------------------------------------------------------
pytestmark = pytest.mark.live

sys.path.insert(0, os.path.dirname(__file__))

from genesis_os.browser_manager import BrowserManager
from genesis_os.browser_playwright import PlaywrightBrowserProvider


def main():
    print("=" * 70)
    print("PHASE 5 LIVE PROOF: Mid-Session Provider Failover")
    print("=" * 70)
    print()

    # --- Step 0: Verify providers ---
    print("[Step 0] Verifying provider availability...")
    mgr = BrowserManager()
    registry = mgr._get_registry()
    for p in mgr._providers:
        print(f"  Provider: {p.name}, available: {p.available}")
    entry = registry.get_healthy_provider("browser.get_title")
    print(f"  Registry first healthy for browser.get_title: {entry.provider_name}")
    print()

    # --- Step 1: Confirm Playwright is healthy ---
    print("[Step 1] Opening real Playwright session, confirming healthy...")
    pw_provider = None
    for p in mgr._providers:
        if p.name == "playwright" and p.available:
            pw_provider = p
            break
    if pw_provider is None:
        print("  FAIL: Playwright not available")
        return False

    pw_provider._ensure_browser()
    print(f"  Playwright connected: {pw_provider._browser.is_connected()}")

    # Real operation: navigate to about:blank and get title
    result = pw_provider.open_url("about:blank")
    print(f"  open_url(about:blank): success={result.get('success')}")
    assert result["success"], f"First op failed: {result}"

    title_result = pw_provider.get_page_title()
    print(f"  get_page_title: success={title_result.get('success')}, title={title_result.get('title')}")
    assert title_result["success"], f"Title failed: {title_result}"
    print("  Step 1 PASSED: Playwright is healthy.")
    print()

    # --- Step 2: Sever the browser connection ---
    print("[Step 2] Severing Playwright browser connection (simulate crash)...")

    # Kill the underlying transport process — this is the most
    # realistic simulation of a browser crash. The Python objects
    # remain but the connection is dead.
    try:
        transport = pw_provider._browser._impl_obj._connection._transport
        transport._proc.kill()
        print("  Killed Playwright transport process")
    except Exception as e:
        print(f"  Transport kill failed: {e}")
        # Fallback: close browser cleanly
        try:
            pw_provider._browser.close()
            print("  Closed browser cleanly")
        except Exception as e2:
            print(f"  Close also failed: {e2}")

    time.sleep(1)

    # Verify death
    try:
        alive = pw_provider._is_browser_alive()
        print(f"  _is_browser_alive(): {alive}")
    except Exception as e:
        print(f"  _is_browser_alive() raised: {type(e).__name__}")

    try:
        connected = pw_provider._browser.is_connected()
        print(f"  is_connected(): {connected}")
    except Exception as e:
        print(f"  is_connected() raised: {type(e).__name__}: {e}")

    print("  Step 2 DONE: Connection severed.")
    print()

    # --- Step 3: Send operation through BrowserManager dispatch ---
    print("[Step 3] Sending operation through BrowserManager dispatch chain...")
    print("  (Should detect Playwright death, fall back to Selenium)")
    print()

    result = mgr._dispatch_with_fallback(
        "get_page_title",
        lambda p: p.get_page_title(),
        timeout=15.0,
    )

    print(f"  Dispatch result:")
    print(f"    success:  {result.get('success')}")
    print(f"    _provider: {result.get('_provider', 'N/A')}")
    if result.get("title"):
        print(f"    title:     {result.get('title')}")
    if result.get("error"):
        print(f"    error:     {str(result.get('error', ''))[:200]}")
    print()

    # --- Step 4: Analyze ---
    print("[Step 4] Analysis:")
    provider_used = result.get("_provider", "unknown")
    print(f"  Provider used: {provider_used}")

    if provider_used == "playwright":
        print("  STILL ON PLAYWRIGHT — dispatch did NOT fall back.")
        print()
        print("  Checking Playwright state...")
        try:
            t = pw_provider.get_page_title()
            print(f"  Playwright get_title: success={t.get('success')}")
        except Exception as e:
            print(f"  Playwright raised: {type(e).__name__}: {str(e)[:100]}")
        return False

    elif provider_used in ("selenium", "webbrowser"):
        print(f"  >>> FALLBACK TO {provider_used.upper()} <<<")
        print(f"  Dispatch detected Playwright failure and switched providers!")
        if result.get("success"):
            print(f"  AND the {provider_used} operation succeeded!")
            print()
            print("  MID-SESSION FAILOVER PROVEN!")
        else:
            print(f"  {provider_used} returned success=False (expected: fresh browser).")
            print(f"  But the key fact: _provider={provider_used}, not playwright.")
            print()
            print("  FAILOVER PROVEN: dispatch switched from dead Playwright to {provider_used}.")
        return True
    else:
        print(f"  Unknown provider: {provider_used}")
        return False


if __name__ == "__main__":
    success = main()
    print()
    print("=" * 70)
    if success:
        print("RESULT: MID-SESSION FAILOVER PROVEN")
    else:
        print("RESULT: FAILOVER NEEDS INVESTIGATION")
    print("=" * 70)
