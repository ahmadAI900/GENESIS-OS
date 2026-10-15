"""Live verification: exercise a real browser navigation through
the new OSManager wrapper to confirm the verification helper
runs and surfaces the genuine post-state check.

Run from the workspace root:
    python backend/_live_verify_browser.py
"""
import json
import sys

sys.path.insert(0, ".")

from genesis_os.os_manager import OSManager


def main():
    print("[live-verify] Initializing OSManager...")
    osm = OSManager()
    print("[live-verify] OSManager initialized.")

    # 1. Real navigate (uses webbrowser.open_url).
    url = "https://example.com"
    print(f"[live-verify] Calling osm.open_url({url!r})...")
    result = osm.open_url(url)
    print("[live-verify] result =", json.dumps(result, indent=2, default=str))
    assert "verified" in result, "OSManager wrapper must expose a verified flag"

    # 2. Real extract / get_url / get_title through the wrapper.
    # These should fail gracefully when no real browser session
    # is attached (the basic WebBrowserProvider returns the
    # success=False honest-failure contract).
    print("[live-verify] Calling osm.browser_get_url()...")
    url_result = osm.browser_get_url()
    print("[live-verify] url_result =", json.dumps(url_result, indent=2, default=str))
    assert "verified" in url_result

    print("[live-verify] Calling osm.browser_get_title()...")
    title_result = osm.browser_get_title()
    print("[live-verify] title_result =", json.dumps(title_result, indent=2, default=str))
    assert "verified" in title_result

    # 3. Real click on a non-existent selector -- the wrapper
    # must report ``verified=False`` honestly with a real reason.
    print("[live-verify] Calling osm.browser_click('#does-not-exist')...")
    click_result = osm.browser_click("#does-not-exist")
    print("[live-verify] click_result =", json.dumps(click_result, indent=2, default=str))
    assert "verified" in click_result
    print(f"[live-verify] click verified={click_result['verified']} "
          f"reason={click_result.get('verification_reason')!r}")
    # The basic WebBrowserProvider does not implement click, so
    # we expect success=False and verified=False.
    assert click_result["verified"] is False, (
        "click on a selector the basic provider cannot service "
        "must NOT report verified=True (no cheap real signal "
        "available)"
    )

    print("[live-verify] All assertions passed.")


if __name__ == "__main__":
    main()