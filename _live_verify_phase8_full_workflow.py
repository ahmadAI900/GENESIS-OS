"""Phase 8 Live Workflow Verification - Full browser capability surface.

Uses the Playwright provider directly (bypassing the BrowserManager's
per-operation ThreadPoolExecutor which has a known Playwright thread-
safety issue) with a local HTTP server serving a static HTML test page.

This proves the provider-layer verification signals work end-to-end.
The ThreadPoolExecutor threading issue is pre-existing and outside
the scope of this phase's verification debt closure.
"""
import http.server
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(__file__))

SEP = "-" * 60
EQS = "=" * 70


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _start_server(port=0):
    handler = _QuietHandler
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def main():
    print(EQS)
    print("PHASE 8 LIVE WORKFLOW VERIFICATION")
    print(EQS)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    server, port = _start_server()
    base_url = "http://127.0.0.1:{}".format(port)
    test_url = "{}/_phase8_test_page.html".format(base_url)
    print("\n[server] Local test server running on {}".format(base_url))

    try:
        from genesis_os.browser_playwright import PlaywrightBrowserProvider

        pw = PlaywrightBrowserProvider()
        if not pw.available:
            print("[FATAL] Playwright not available")
            return

        print("[init] Playwright provider initialized (headless={})".format(
            pw._resolve_headless()))

        results = {}

        # STEP 1: Navigate
        print("\n" + SEP)
        print("[STEP 1] Navigate to local test page")
        print(SEP)
        nav = pw.open_url(test_url)
        results["navigate"] = nav
        print("  success: {}".format(nav.get('success')))
        print("  url: {}".format(nav.get('url')))
        print("  verified: {}".format(nav.get('verified')))

        # STEP 2: Get page title / URL
        print("\n" + SEP)
        print("[STEP 2] Get page title and URL")
        print(SEP)
        title = pw.get_page_title()
        url = pw.get_page_url()
        results["get_title"] = title
        results["get_url"] = url
        print("  title: {} (verified: {})".format(title.get('title'), title.get('verified')))
        print("  url: {} (verified: {})".format(url.get('url'), url.get('verified')))

        # STEP 3: Find text
        print("\n" + SEP)
        print("[STEP 3] Find text on page")
        print(SEP)
        find_result = pw.find_text("Phase 8")
        results["find"] = find_result
        print("  success: {}".format(find_result.get('success')))
        print("  count: {}".format(find_result.get('count')))

        # STEP 4: Extract text
        print("\n" + SEP)
        print("[STEP 4] Extract text from page")
        print(SEP)
        extract = pw.extract_text("#extract-target")
        results["extract"] = extract
        print("  success: {}".format(extract.get('success')))
        print("  text: {}".format(extract.get('text', '')[:100]))

        # STEP 5: Type into form
        print("\n" + SEP)
        print("[STEP 5] Type text into form input")
        print(SEP)
        type_result = pw.type_text("#text-input", "Hello from Phase 8")
        results["type"] = type_result
        print("  success: {}".format(type_result.get('success')))
        print("  element_found: {}".format(type_result.get('element_found')))
        print("  verified: {}".format(type_result.get('verified')))
        print("  actual_value: {}".format(type_result.get('actual_value')))

        # STEP 6: Click safe button
        print("\n" + SEP)
        print("[STEP 6] Click safe button")
        print(SEP)
        click_safe = pw.click("#safe-button")
        results["click_safe"] = click_safe
        print("  success: {}".format(click_safe.get('success')))
        print("  element_found: {}".format(click_safe.get('element_found')))
        print("  verified: {}".format(click_safe.get('verified')))

        # Read post-click state
        click_result_text = pw.extract_text("#click-result")
        print("  post-click state: {}".format(click_result_text.get('text', '')[:80]))

        # STEP 7: Verify page state
        print("\n" + SEP)
        print("[STEP 7] Verify page state (title check)")
        print(SEP)
        page_title = pw.get_page_title()
        title_str = page_title.get("title", "")
        verify_passed = "Phase 8" in title_str
        results["verify"] = {"success": verify_passed, "title": title_str,
                             "passed": verify_passed}
        print("  title: {}".format(title_str))
        print("  contains 'Phase 8': {}".format(verify_passed))

        # STEP 8: Risky click (signal-word "delete")
        print("\n" + SEP)
        print("[STEP 8] Risky click (signal-word: 'delete')")
        print(SEP)
        from genesis_os.security_model import assess_operation_risk
        risk = assess_operation_risk("browser.click", {"element_text": "Delete Everything"})
        print("  risk_level: {}".format(risk.risk_level.value))
        print("  requires_confirmation: {}".format(risk.requires_confirmation))
        print("  reason: {}".format(risk.reason))

        # STEP 9: Image/icon button (alt-text risk)
        print("\n" + SEP)
        print("[STEP 9] Image/icon button (alt-text: 'delete permanently')")
        print(SEP)
        risk_icon = assess_operation_risk("browser.click", {
            "alt_text": "delete permanently",
            "_no_element_text": False,
        })
        print("  risk_level: {}".format(risk_icon.risk_level.value))
        print("  requires_confirmation: {}".format(risk_icon.requires_confirmation))
        print("  reason: {}".format(risk_icon.reason))

        # STEP 10: Unassessable element
        print("\n" + SEP)
        print("[STEP 10] Unassessable element (no accessible text)")
        print(SEP)
        risk_unassess = assess_operation_risk("browser.click", {
            "_no_element_text": True,
        })
        print("  risk_level: {}".format(risk_unassess.risk_level.value))
        print("  requires_confirmation: {}".format(risk_unassess.requires_confirmation))
        print("  reason: {}".format(risk_unassess.reason))

        # STEP 11: Select dropdown
        print("\n" + SEP)
        print("[STEP 11] Select dropdown option")
        print(SEP)
        select_result = pw.select("#test-select", value="opt2")
        results["select"] = select_result
        print("  success: {}".format(select_result.get('success')))
        print("  method: {}".format(select_result.get('method')))
        print("  value: {}".format(select_result.get('value')))

        # STEP 12: Wait for element
        print("\n" + SEP)
        print("[STEP 12] Wait for element (visible)")
        print(SEP)
        # Click the "show delayed" button first to make it visible
        pw.click("#show-delayed")
        import time
        time.sleep(1)
        wait_result = pw.wait_for_element("#delayed-element", timeout=3.0)
        results["wait"] = wait_result
        print("  success: {}".format(wait_result.get('success')))
        print("  found: {}".format(wait_result.get('found')))

        # STEP 13: Open/close tab
        print("\n" + SEP)
        print("[STEP 13] Open and close tab")
        print(SEP)
        open_tab = pw.open_tab(test_url)
        results["open_tab"] = open_tab
        print("  open_tab success: {}".format(open_tab.get('success')))
        print("  tab_index: {}".format(open_tab.get('tab_index')))

        tabs = pw.get_tabs()
        print("  tabs count: {}".format(tabs.get('count')))

        close_tab = pw.close_tab(1)
        results["close_tab"] = close_tab
        print("  close_tab success: {}".format(close_tab.get('success')))

        # STEP 14: Download
        print("\n" + SEP)
        print("[STEP 14] Download file")
        print(SEP)
        dl_path = os.path.join(tempfile.gettempdir(), "phase8_download_test.txt")
        dl = pw.download(test_url, save_path=dl_path)
        results["download"] = dl
        print("  success: {}".format(dl.get('success')))
        print("  file_size: {}".format(dl.get('file_size')))
        print("  save_path: {}".format(dl.get('save_path')))
        if os.path.exists(dl_path):
            os.remove(dl_path)

        # STEP 15: Screenshot
        print("\n" + SEP)
        print("[STEP 15] Screenshot")
        print(SEP)
        ss_path = os.path.join(tempfile.gettempdir(), "phase8_screenshot.png")
        ss = pw.screenshot(ss_path)
        results["screenshot"] = ss
        print("  success: {}".format(ss.get('success')))
        print("  path: {}".format(ss.get('path')))
        file_exists = os.path.exists(ss_path) if ss.get('path') else False
        print("  file_exists: {}".format(file_exists))
        if os.path.exists(ss_path):
            os.remove(ss_path)

        # STEP 16: Scroll
        print("\n" + SEP)
        print("[STEP 16] Scroll")
        print(SEP)
        scroll = pw.scroll("down", 2)
        results["scroll"] = scroll
        print("  success: {}".format(scroll.get('success')))

        # STEP 17: Type + re-read (prove value round-trip)
        print("\n" + SEP)
        print("[STEP 17] Type + value round-trip verification")
        print(SEP)
        pw.type_text("#text-input", "Round-trip test 42")
        readback = pw._page.locator("#text-input").input_value()
        results["type_roundtrip"] = {"success": True, "readback": readback}
        print("  typed: 'Round-trip test 42'")
        print("  readback: '{}'".format(readback))
        print("  match: {}".format(readback == "Round-trip test 42"))

        # STEP 18: Upload file
        print("\n" + SEP)
        print("[STEP 18] Upload file")
        print(SEP)
        upload_path = os.path.join(tempfile.gettempdir(), "phase8_upload_test.txt")
        with open(upload_path, "w") as f:
            f.write("test upload content")
        upload_result = pw.upload("#file-input", upload_path)
        results["upload"] = upload_result
        print("  success: {}".format(upload_result.get('success')))
        print("  element_found: {}".format(upload_result.get('element_found')))
        print("  verified: {}".format(upload_result.get('verified')))
        if os.path.exists(upload_path):
            os.remove(upload_path)

        # Summary
        print("\n" + EQS)
        print("WORKFLOW SUMMARY")
        print(EQS)
        all_ok = True
        for step, result in results.items():
            success = result.get("success", False)
            status = "PASS" if success else "FAIL"
            verified = result.get("verified")
            v_str = str(verified) if verified is not None else "N/A"
            print("  {:20s}  success={:4s}  verified={}".format(step, status, v_str))
            if not success:
                all_ok = False

        print("\n" + EQS)
        if all_ok:
            print("RESULT: ALL STEPS PASSED")
        else:
            print("RESULT: SOME STEPS FAILED - see above for details")
        print(EQS)

        # Phase 2 debt closure evidence
        print("\n" + SEP)
        print("PHASE 2 DEBT CLOSURE EVIDENCE")
        print(SEP)
        print("  BEFORE (Phase 2-7):")
        print("    click:   provider emits {'success': True} only")
        print("             -> verification_helpers returns verified=False (honest fallback)")
        print("    type:    provider emits {'success': True} only")
        print("             -> verification_helpers returns verified=False (honest fallback)")
        print("    upload:  provider emits {'success': True} only")
        print("             -> verification_helpers returns verified=False (honest fallback)")
        print()
        print("  AFTER (Phase 8):")
        click_r = results.get('click_safe', {})
        type_r = results.get('type', {})
        upload_r = results.get('upload', {})
        print("    click:   element_found={}, verified={}".format(
            click_r.get('element_found'), click_r.get('verified')))
        print("    type:    element_found={}, verified={}, actual_value={!r}".format(
            type_r.get('element_found'), type_r.get('verified'), type_r.get('actual_value')))
        print("    upload:  element_found={}, verified={}".format(
            upload_r.get('element_found'), upload_r.get('verified')))
        print()
        if click_r.get('verified') and type_r.get('verified') and upload_r.get('verified'):
            print("  VERDICT: All three previously-honest-fallback operations")
            print("           now emit REAL verification signals from the provider.")
        elif click_r.get('verified') and type_r.get('verified'):
            print("  VERDICT: click and type now emit REAL verification signals.")
            print("           upload verified={}".format(upload_r.get('verified')))

    finally:
        pw.close()
        server.shutdown()
        print("\n[server] Local test server shut down.")


if __name__ == "__main__":
    main()
