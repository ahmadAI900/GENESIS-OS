"""Live verification 3: real browser_click on a REAL existing element.

Opens example.com (a real, well-known page) and clicks the first
existing <a> element (the "Learn more" link). This proves whether
the OSManager.browser_click wrapper -- when the underlying provider
returns success=True for a click that actually landed on a real DOM
element -- reports verified=True or verified=False.

The expectation based on the source code: the playwright provider
returns {"success": True, "selector": ...} without any
``element_found`` / ``verified`` signal. The OSManager
``verify_browser_click`` helper therefore returns
``verified=False`` with the "honest fallback" reason. This is the
honest-but-permanently-conservative result the directive asks us to
make explicit, not silently accept.
"""
import json
import sys

sys.path.insert(0, ".")

from genesis_os.os_manager import OSManager


def main():
    print("[live-verify-click] Initializing OSManager...")
    osm = OSManager()
    print("[live-verify-click] OSManager initialized.")

    # 1. Open a real page.
    print("[live-verify-click] Navigating to https://example.com ...")
    nav = osm.open_url("https://example.com")
    print("[live-verify-click] nav =", json.dumps(nav, indent=2, default=str))

    # 2. Extract the visible text of <a> elements to discover
    #    the actual text on the page. example.com has one <a>
    #    with text "Learn more" and href to iana.org.
    print("[live-verify-click] Extracting <a> text via browser_extract('a')...")
    extract = osm.browser_extract("a")
    print("[live-verify-click] extract =", json.dumps(extract, indent=2, default=str)[:800])

    # 3. Now click the real existing element by its actual text.
    real_selector = "text=Learn more"
    print(f"[live-verify-click] Calling osm.browser_click({real_selector!r}) "
          f"-- this IS a real existing element on the page...")
    click_result = osm.browser_click(real_selector)
    print("[live-verify-click] click_result =", json.dumps(click_result, indent=2, default=str))

    # The honest assertion: even though the click landed on a real
    # DOM element and the provider reports success=True, the helper
    # cannot observe element_found / verified from the provider's
    # output alone, so verified=False is the honest answer.
    if click_result["success"] is True:
        if click_result["verified"] is False:
            print(
                "[live-verify-click] HONEST-CONSERVATIVE: provider said success=True "
                "but the provider's result has no element_found / verified signal. "
                "Wrapper reports verified=False with the honest-fallback reason."
            )
            assert "honest fallback" in click_result.get("verification_reason", "").lower()
        else:
            print(
                "[live-verify-click] verified=True: a real post-state signal "
                "was present in the provider's result."
            )
            print(f"  reason: {click_result.get('verification_reason')!r}")
    else:
        print("[live-verify-click] Provider reported failure:", click_result.get("error"))

    # Also try by CSS selector for completeness.
    css_selector = "a"
    print(f"\n[live-verify-click] Also trying CSS selector {css_selector!r} ...")
    click_css = osm.browser_click(css_selector)
    print("[live-verify-click] click_css =", json.dumps(click_css, indent=2, default=str))
    if click_css["success"] is True:
        print(
            f"[live-verify-click] success=True; verified={click_css['verified']}; "
            f"reason={click_css.get('verification_reason')!r}"
        )

    print("[live-verify-click] Done.")


if __name__ == "__main__":
    main()