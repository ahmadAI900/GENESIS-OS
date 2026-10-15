"""
Verification Honesty Sweep — Phase 2 Regression Tests.

These tests enforce the post-state verification contract the
``verification_honesty_sweep.md`` directive applied to the
remaining SELF_REPORTED_ONLY capabilities the Phase 0 audit
flagged.

Coverage:

    1. ``OSManager`` ``document.*`` wrappers — verified is now
       bound to real, observable post-state evidence (file
       exists, content matches, payload structure), not to
       ``result.success``. Both directions are exercised:

           a. positive -- create a real file on disk and confirm
              ``verified=True`` flows through the wrapper.
           b. negative -- simulate the provider reporting
              ``success=True`` while the underlying file was
              NOT actually created (e.g. monkeypatching the
              provider's create method to lie), and confirm
              the wrapper now reports ``verified=False`` with
              an explicit reason rather than the previous
              ``verified=True`` conflation.

    2. ``OSManager`` ``spreadsheet.*`` wrappers — same contract
       for inspect / read / sort / filter / calculate / rank /
       group_by / aggregate / compare.

    3. ``OSManager`` ``browser.*`` wrappers — verified is now
       bound to real, observable post-state evidence (provider-
       reported URL / element_found / count / file-on-disk),
       not to ``success``. Both directions are exercised.

    4. ``gui.click`` / ``gui.double_click`` / ``gui.scroll`` /
       ``gui.keyboard_action`` with ``target=None`` MUST now
       surface ``unresolved_target`` with ``verified=False``
       when no safe focused window exists. The previous
       ``missing_target`` / fake-success carve-out is replaced
       with the runtime-focus-resolver contract.

The style follows ``test_bucket1_verification_regression.py``
and ``test_phase1_gui_focus_verification.py`` -- both positive
and negative cases, not just happy-path.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.enhanced_observation import EnhancedObservationLoop
from genesis_os.os_manager import OSManager
from genesis_os.verification_helpers import (
    verify_doc_create,
    verify_doc_edit,
    verify_doc_inspect,
    verify_doc_read,
    verify_doc_search,
    verify_doc_compare,
    verify_doc_summarize,
    verify_doc_transform,
    verify_doc_verify,
    verify_sheet_inspect,
    verify_sheet_read,
    verify_sheet_sort,
    verify_sheet_filter,
    verify_sheet_calculate,
    verify_sheet_rank,
    verify_sheet_group_by,
    verify_sheet_aggregate,
    verify_sheet_compare,
    verify_browser_click,
    verify_browser_scroll,
    verify_browser_type,
    verify_browser_extract,
    verify_browser_find,
    verify_browser_title,
    verify_browser_tab_mgmt,
    verify_browser_wait,
    verify_browser_screenshot,
    verify_browser_select,
    verify_browser_download,
    verify_browser_upload,
    verify_browser_verify,
    verify_browser_capabilities,
    verify_browser_navigate,
    verify_data_inspect,
    verify_data_transform,
)


# =========================================================
# HELPERS
# =========================================================


def _make_osm_with_doc_intel(doc_intel) -> OSManager:
    """Build an OSManager with a stubbed doc_intel so we can
    exercise the wrappers without spinning up the real
    DocumentIntelligence.

    doc_intel may be a real DocumentIntelligence() instance
    (the integration tests) or a MagicMock that returns shaped
    DocumentResult objects (the negative tests).
    """
    osm = OSManager.__new__(OSManager)
    osm.doc_intel = doc_intel
    osm.sheet_intel = None
    osm.gui = None
    osm.browser = MagicMock()
    osm.network = MagicMock()
    osm.doc_intel_available = doc_intel is not None
    return osm


def _make_osm_with_sheet_intel(sheet_intel) -> OSManager:
    osm = OSManager.__new__(OSManager)
    osm.doc_intel = None
    osm.sheet_intel = sheet_intel
    osm.gui = None
    osm.browser = MagicMock()
    osm.network = MagicMock()
    return osm


def _make_osm_with_browser(browser_mock) -> OSManager:
    osm = OSManager.__new__(OSManager)
    osm.doc_intel = None
    osm.sheet_intel = None
    osm.gui = None
    osm.browser = browser_mock
    osm.network = MagicMock()
    return osm


class _FakeUser32:
    """Minimal user32 stand-in for the focus resolver path."""

    def __init__(self, focused_title: str = "Notepad", focused_hwnd: int = 12345) -> None:
        self._focused_title = focused_title
        self._focused_hwnd = focused_hwnd

    def GetForegroundWindow(self):
        return self._focused_hwnd

    def GetWindowTextLengthW(self, hwnd):
        if hwnd != self._focused_hwnd:
            return 0
        return len(self._focused_title)

    def GetWindowTextW(self, hwnd, buf, max_count):
        if hwnd != self._focused_hwnd:
            return 0
        title = self._focused_title
        if len(title) < max_count:
            buf.value = title
        else:
            buf.value = title[: max_count - 1]
        return min(max_count - 1, len(title))

    def GetWindowThreadProcessId(self, hwnd, pid_ref):
        pid_ref.value = 9999
        return 1


# =========================================================
# 1. DOCUMENT HELPERS — both directions
# =========================================================


def test_verify_doc_create_positive(tmp_path):
    """``verify_doc_create`` returns ``verified=True`` when the
    provider reported success and the file actually exists on disk.
    """
    path = str(tmp_path / "real.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("hello")
    v = verify_doc_create(True, path, {"size": 5})
    assert v["verified"] is True
    assert "non-empty" in v["reason"] or "exists" in v["reason"]


def test_verify_doc_create_negative_missing_file(tmp_path):
    """Provider says ``success=True`` but the file is missing on
    disk. The helper MUST report ``verified=False`` with an
    explicit reason -- not ``verified=True`` like the old
    ``verified=result.success`` conflation.
    """
    path = str(tmp_path / "missing.txt")  # never created
    v = verify_doc_create(True, path, {"size": 100})
    assert v["verified"] is False
    assert "missing" in v["reason"].lower() or "empty" in v["reason"].lower()


def test_verify_doc_create_negative_provider_failure(tmp_path):
    """When the provider reports failure the helper reports
    ``verified=False`` regardless of any disk state.
    """
    path = str(tmp_path / "real.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("hi")
    v = verify_doc_create(False, path, {"size": 2})
    assert v["verified"] is False
    assert "failure" in v["reason"].lower() or "fail" in v["reason"].lower()


def test_verify_doc_edit_positive(tmp_path):
    """``verify_doc_edit`` reads the file back and confirms the
    replacement text is actually present.
    """
    path = str(tmp_path / "edit.txt")
    # File already contains the replacement text -- simulates
    # a successful edit landing on disk.
    with open(path, "w", encoding="utf-8") as f:
        f.write("goodbye world")
    v = verify_doc_edit(
        True,
        path,
        {"find_text": "hello", "replace_text": "goodbye", "occurrences": 1},
    )
    assert v["verified"] is True


def test_verify_doc_edit_negative_replacement_missing(tmp_path):
    """Provider says ``success=True`` but the file on disk does
    NOT contain the replacement text. The helper MUST report
    ``verified=False`` (this is exactly the silent false-success
    the directive prevents).
    """
    path = str(tmp_path / "edit.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("hello world")
    # Simulate the provider claiming replace_text was "goodbye"
    # but the file still says "hello".
    v = verify_doc_edit(
        True,
        path,
        {"find_text": "hello", "replace_text": "goodbye", "occurrences": 1},
    )
    assert v["verified"] is False
    assert "does not contain" in v["reason"]


def test_verify_doc_inspect_positive(tmp_path):
    path = str(tmp_path / "doc.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("hello")
    v = verify_doc_inspect(True, path, {"size": 5})
    assert v["verified"] is True


def test_verify_doc_inspect_negative():
    v = verify_doc_inspect(True, "/nonexistent/path/file.txt", {})
    assert v["verified"] is False


def test_verify_doc_read_negative_empty_text(tmp_path):
    """Provider returns ``success=True`` with empty text payload
    -- an honest helper must NOT report ``verified=True``.
    """
    path = str(tmp_path / "empty.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("")
    v = verify_doc_read(True, path, {"text": "", "word_count": 0})
    assert v["verified"] is False


def test_verify_doc_search_negative_no_matches_field():
    v = verify_doc_search(True, "/tmp/x.txt", {})
    assert v["verified"] is False


def test_verify_doc_compare_negative_missing_file(tmp_path):
    path1 = str(tmp_path / "a.txt")
    path2 = str(tmp_path / "b.txt")  # missing
    with open(path1, "w", encoding="utf-8") as f:
        f.write("a")
    v = verify_doc_compare(
        True,
        path1,
        {"path1": path1, "path2": path2, "similarity": 0.5},
    )
    assert v["verified"] is False


def test_verify_doc_summarize_negative_empty_summary(tmp_path):
    path = str(tmp_path / "x.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("text")
    v = verify_doc_summarize(
        True,
        path,
        {"summary": "", "original_length": 4, "summary_length": 0},
    )
    assert v["verified"] is False


def test_verify_doc_transform_negative_missing_output(tmp_path):
    """Provider says ``success=True`` but the output file is not
    on disk. The helper must report ``verified=False``.
    """
    out = str(tmp_path / "out.html")  # never created
    v = verify_doc_transform(
        True,
        "/tmp/x.txt",
        {
            "source_path": "/tmp/x.txt",
            "output_path": out,
            "output_format": "html",
            "content_length": 100,
        },
    )
    assert v["verified"] is False


def test_verify_doc_verify_negative_all_passed_false(tmp_path):
    """When the provider's verify explicitly reports
    ``all_passed=False`` the helper reports ``verified=False``.
    """
    path = str(tmp_path / "x.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("text")
    v = verify_doc_verify(
        True,
        path,
        {
            "checks": [
                {"check": "exists", "passed": True},
                {"check": "content", "passed": False, "expected_snippet": "x"},
            ],
            "all_passed": False,
        },
    )
    assert v["verified"] is False


def test_verify_doc_verify_positive(tmp_path):
    path = str(tmp_path / "x.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("expected snippet")
    v = verify_doc_verify(
        True,
        path,
        {
            "checks": [
                {"check": "exists", "passed": True},
                {"check": "content", "passed": True},
            ],
            "all_passed": True,
        },
    )
    assert v["verified"] is True


# =========================================================
# 2. SPREADSHEET HELPERS — both directions
# =========================================================


def test_verify_sheet_inspect_positive(tmp_path):
    path = str(tmp_path / "data.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
    v = verify_sheet_inspect(True, path, {})
    assert v["verified"] is True


def test_verify_sheet_inspect_negative_missing_file():
    v = verify_sheet_inspect(True, "/nonexistent/missing.csv", {})
    assert v["verified"] is False


def test_verify_sheet_read_negative_empty_rows():
    v = verify_sheet_read(True, "/tmp/x.csv", [])
    assert v["verified"] is False


def test_verify_sheet_sort_negative_missing_output(tmp_path):
    out = str(tmp_path / "sorted.csv")  # never created
    v = verify_sheet_sort(True, out, {"output": out})
    assert v["verified"] is False


def test_verify_sheet_sort_rejects_wrong_order(tmp_path):
    out = tmp_path / "wrong_order.csv"
    out.write_text("Name,Score\nAlice,2\nBob,9\n", encoding="utf-8")
    v = verify_sheet_sort(
        True,
        str(out),
        {"output": str(out), "column": "Score", "descending": True},
    )
    assert v["verified"] is False


def test_verify_sheet_calculate_negative_no_column(tmp_path):
    path = str(tmp_path / "x.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
    v = verify_sheet_calculate(True, path, {"calculated_column": None})
    assert v["verified"] is False


def test_verify_sheet_rank_negative_missing_output(tmp_path):
    out = str(tmp_path / "ranked.csv")  # missing
    v = verify_sheet_rank(True, out, {"output": out})
    assert v["verified"] is False


def test_verify_sheet_group_by_negative_no_groups(tmp_path):
    path = str(tmp_path / "x.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
    v = verify_sheet_group_by(True, path, {"groups": None})
    assert v["verified"] is False


def test_verify_sheet_aggregate_negative_no_aggregates(tmp_path):
    path = str(tmp_path / "x.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
    v = verify_sheet_aggregate(True, path, {"aggregates": None, "results": None})
    assert v["verified"] is False


def test_verify_sheet_compare_negative_missing_one_file(tmp_path):
    p1 = str(tmp_path / "a.csv")
    with open(p1, "w", encoding="utf-8") as f:
        f.write("a\n")
    v = verify_sheet_compare(
        True,
        p1,
        {"path1": p1, "path2": "/nonexistent/b.csv"},
    )
    assert v["verified"] is False


def test_verify_sheet_filter_negative_zero_rows(tmp_path):
    path = str(tmp_path / "x.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
    v = verify_sheet_filter(
        True,
        path,
        {"filtered_count": 0, "kept_count": 0},
    )
    assert v["verified"] is False


# =========================================================
# 3. BROWSER HELPERS — both directions
# =========================================================


def test_verify_browser_click_positive_postcondition_readback():
    v = verify_browser_click(
        True,
        {"click_postcondition_verified": True},
    )
    assert v["verified"] is True


def test_verify_browser_click_rejects_element_presence_only():
    v = verify_browser_click(
        True,
        {"element_found": True, "post_state_matches": True},
    )
    assert v["verified"] is False


def test_verify_browser_click_negative_no_signal():
    """No element_found / verified / URL signal. Honest helper
    reports ``verified=False`` rather than faking True.
    """
    v = verify_browser_click(True, {"success": True})
    assert v["verified"] is False


def test_verify_browser_click_negative_provider_failure():
    v = verify_browser_click(False, {"element_found": True})
    assert v["verified"] is False


def test_verify_browser_scroll_positive():
    v = verify_browser_scroll(True, {"scroll_position_changed": True})
    assert v["verified"] is True


def test_verify_browser_scroll_negative_presence_only():
    v = verify_browser_scroll(True, {"element_found": True})
    assert v["verified"] is False


def test_verify_browser_type_negative_no_signal():
    v = verify_browser_type(True, {"success": True})
    assert v["verified"] is False


def test_verify_browser_extract_positive():
    v = verify_browser_extract(True, {"text": "hello world"})
    assert v["verified"] is True


def test_verify_browser_extract_negative_empty_text():
    v = verify_browser_extract(True, {"text": ""})
    assert v["verified"] is False


def test_verify_browser_find_positive_with_count():
    v = verify_browser_find(True, {"count": 3})
    assert v["verified"] is True


def test_verify_browser_find_negative_no_count():
    v = verify_browser_find(True, {"success": True})
    assert v["verified"] is False


def test_verify_browser_title_positive():
    v = verify_browser_title(True, {"title": "Example Page"})
    assert v["verified"] is True


def test_verify_browser_title_negative_empty():
    v = verify_browser_title(True, {"title": ""})
    assert v["verified"] is False


def test_verify_browser_tab_mgmt_positive():
    v = verify_browser_tab_mgmt(
        True,
        {"tab_index": 1, "tab_state_verified": True},
    )
    assert v["verified"] is True


def test_verify_browser_tab_mgmt_negative():
    v = verify_browser_tab_mgmt(True, {"success": True})
    assert v["verified"] is False


def test_verify_browser_wait_positive_element_found():
    v = verify_browser_wait(True, {"element_found": True})
    assert v["verified"] is True


def test_verify_browser_wait_negative_failure():
    v = verify_browser_wait(False, {})
    assert v["verified"] is False


def test_verify_browser_screenshot_positive_file_exists(tmp_path):
    path = str(tmp_path / "shot.png")
    with open(path, "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * 100)
    v = verify_browser_screenshot(True, {"path": path})
    assert v["verified"] is True


def test_verify_browser_screenshot_negative_missing_file():
    v = verify_browser_screenshot(True, {"path": "/nonexistent/shot.png"})
    assert v["verified"] is False


def test_verify_browser_select_positive():
    v = verify_browser_select(
        True,
        {"selected_value": "us-east", "selection_verified": True},
    )
    assert v["verified"] is True


def test_verify_browser_select_negative_no_signal():
    v = verify_browser_select(True, {"success": True})
    assert v["verified"] is False


def test_verify_browser_download_positive(tmp_path):
    path = str(tmp_path / "downloaded.zip")
    with open(path, "wb") as f:
        f.write(b"\x00" * 1024)
    v = verify_browser_download(True, {"save_path": path})
    assert v["verified"] is True


def test_verify_browser_download_negative_missing_file():
    v = verify_browser_download(True, {"save_path": "/nonexistent/file.zip"})
    assert v["verified"] is False


def test_verify_browser_upload_negative_no_signal():
    v = verify_browser_upload(True, {"success": True})
    assert v["verified"] is False


def test_verify_browser_verify_positive_all_checks_passed():
    v = verify_browser_verify(
        True,
        {
            "checks": [
                {"check": "url", "passed": True},
                {"check": "title", "passed": True},
            ]
        },
    )
    assert v["verified"] is True


def test_verify_browser_verify_negative_one_failed():
    v = verify_browser_verify(
        True,
        {
            "checks": [
                {"check": "url", "passed": True},
                {"check": "title", "passed": False},
            ]
        },
    )
    assert v["verified"] is False


def test_verify_browser_verify_negative_no_checks():
    v = verify_browser_verify(True, {})
    assert v["verified"] is False


def test_verify_browser_capabilities_positive():
    v = verify_browser_capabilities(True, {"provider": "playwright"})
    assert v["verified"] is True


def test_verify_browser_capabilities_negative_no_provider():
    v = verify_browser_capabilities(True, {})
    assert v["verified"] is False


def test_verify_browser_navigate_positive():
    v = verify_browser_navigate(
        True,
        {
            "url": "https://example.com",
            "requested_url": "https://example.com",
            "verified": True,
        },
    )
    assert v["verified"] is True


def test_verify_browser_navigate_negative_no_url():
    v = verify_browser_navigate(True, {})
    assert v["verified"] is False


def test_verify_browser_navigate_rejects_wrong_observed_url():
    v = verify_browser_navigate(
        True,
        {
            "requested_url": "https://example.com",
            "url": "https://other.example",
            "verified": True,
        },
    )
    assert v["verified"] is False


def test_enhanced_observation_requires_matching_browser_url():
    osm = OSManager.__new__(OSManager)
    osm.browser_get_title = MagicMock(return_value={"success": True, "title": "Example"})
    osm.browser_get_url = MagicMock(return_value={"success": True, "url": "https://other.example"})
    osm.browser_get_tabs = MagicMock(return_value={"success": True, "count": 1})
    plan = ActionPlan(operation="browser.open_url", target="https://example.com")
    execution = ActionResult.success_result(
        operation="browser.open_url",
        target=plan.target,
        application=None,
        message="opened",
        verified=True,
        verification={"url_readback": True, "actual_url": "https://other.example"},
    )

    result = EnhancedObservationLoop(osm).observe("step-1", plan, execution)

    assert result.matches_expected is False
    assert "URL mismatch" in (result.discrepancy or "")


# ============================================================
# 3b. BROWSER URL SPOOFING — the evidence gate must compare URL
#      STRUCTURE, not prefixes.
#
#      Regression: contracts.has_meaningful_result_evidence used
#      ``actual.startswith(requested)``, so a request for
#      "https://example.com" verified against
#      "https://example.com.evil.net/" and against the userinfo form
#      "https://example.com@evil.net/" (real host: evil.net).
#      Live via browser_selenium.py / browser_playwright.py, which both
#      populate requested_url/actual_url on browser.open_url.
# ============================================================


def _open_url_evidence(requested: str, actual: str) -> ActionResult:
    return ActionResult.success_result(
        operation="browser.open_url",
        target=requested,
        application="chrome",
        message="opened",
        executed=True,
        verified=True,
        verification={"requested_url": requested, "actual_url": actual},
    )


class TestBrowserUrlSpoofingRejected:
    @pytest.mark.parametrize(
        "requested,actual",
        [
            ("https://example.com", "https://example.com.evil.net/"),
            ("https://example.com", "https://example.com@evil.net/"),
            ("https://example.com", "https://example.com.attacker.io/x"),
            ("https://example.com/a", "https://example.com/a/../b"),
            ("https://example.com", "https://example.com/admin"),
            ("https://example.com", "http://example.com"),
            ("https://example.com", "https://example.com:8443"),
            ("https://example.com/?a=1", "https://example.com/?a=2"),
        ],
    )
    def test_spoofed_or_mismatched_url_is_not_meaningful(
        self, requested, actual
    ):
        from genesis_os.contracts import has_meaningful_result_evidence

        assert has_meaningful_result_evidence(
            _open_url_evidence(requested, actual)
        ) is False

    @pytest.mark.parametrize(
        "requested,actual",
        [
            ("https://example.com", "https://example.com"),
            ("https://example.com", "https://example.com/"),
            ("https://Example.COM", "https://example.com"),
            ("https://example.com", "https://example.com:443"),
            ("http://example.com", "https://example.com"),
            ("https://example.com", "https://example.com/#top"),
        ],
    )
    def test_documented_tolerances_still_verify(
        self, requested, actual
    ):
        """The tolerated differences, pinned so they cannot be widened
        silently: host/scheme case, default port, trailing slash and
        empty-path equivalence, fragment difference, and a directional
        http->https upgrade."""
        from genesis_os.contracts import has_meaningful_result_evidence

        assert has_meaningful_result_evidence(
            _open_url_evidence(requested, actual)
        ) is True

    def test_url_comparison_is_order_independent_of_value_type(self):
        from genesis_os.contracts import urls_denote_same_resource

        assert urls_denote_same_resource("https://a.test", "https://a.test") is True
        assert urls_denote_same_resource("https://a.test", "https://a.test.evil/") is False
        assert urls_denote_same_resource(None, "https://a.test") is False
        assert urls_denote_same_resource("https://a.test", None) is False
        assert urls_denote_same_resource("", "") is False


# =========================================================
# 4. OSManager.doc_* wrappers — end-to-end both directions
# =========================================================


def test_osm_doc_create_positive_verified_true(tmp_path):
    """OSManager.doc_create must report ``verified=True`` when
    the file is actually on disk.
    """
    path = str(tmp_path / "real.txt")
    doc_intel = MagicMock()
    from genesis_os.document_intelligence import DocumentFormat, DocumentResult

    doc_intel.create_txt.return_value = DocumentResult(
        success=True,
        operation="create_txt",
        path=path,
        format=DocumentFormat.TXT,
        message="OK",
        data={"size": 5},
        error=None,
    )
    # Side effect: actually create the file.
    with open(path, "w", encoding="utf-8") as f:
        f.write("hello")
    osm = _make_osm_with_doc_intel(doc_intel)
    result = osm.doc_create(path, doc_type="txt", content="hello")
    assert result["success"] is True
    assert result["verified"] is True


def test_osm_doc_create_negative_verified_false_when_file_missing(tmp_path):
    """OSManager.doc_create must report ``verified=False`` when
    the provider claims success but the file is NOT on disk.
    This is the regression test for the previous
    ``verified=result.success`` conflation.
    """
    path = str(tmp_path / "phantom.txt")
    doc_intel = MagicMock()
    from genesis_os.document_intelligence import DocumentFormat, DocumentResult

    doc_intel.create_txt.return_value = DocumentResult(
        success=True,  # provider lies about success
        operation="create_txt",
        path=path,
        format=DocumentFormat.TXT,
        message="OK",
        data={"size": 100},
        error=None,
    )
    # File is NOT actually created.
    osm = _make_osm_with_doc_intel(doc_intel)
    result = osm.doc_create(path, doc_type="txt", content="hello")
    assert result["success"] is True  # provider said success
    assert result["verified"] is False  # wrapper caught the lie
    assert result.get("verification_reason")
    assert "missing" in result["verification_reason"].lower() or "empty" in result["verification_reason"].lower()


def test_osm_doc_edit_negative_when_replacement_missing(tmp_path):
    """OSManager.doc_edit must report ``verified=False`` when
    the file does not contain the replacement text after edit.
    """
    path = str(tmp_path / "edit.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("original content")
    doc_intel = MagicMock()
    from genesis_os.document_intelligence import DocumentFormat, DocumentResult

    # Provider claims it replaced "original" with "updated" but
    # the file still says "original".
    doc_intel.edit.return_value = DocumentResult(
        success=True,
        operation="edit",
        path=path,
        format=DocumentFormat.TXT,
        message="OK",
        data={"find_text": "original", "replace_text": "updated", "occurrences": 1},
        error=None,
    )
    osm = _make_osm_with_doc_intel(doc_intel)
    result = osm.doc_edit(path, "original", "updated")
    assert result["success"] is True  # provider said success
    assert result["verified"] is False  # wrapper caught the lie
    assert "does not contain" in result["verification_reason"]


def test_osm_doc_read_negative_empty_payload(tmp_path):
    path = str(tmp_path / "empty.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("")
    doc_intel = MagicMock()
    from genesis_os.document_intelligence import DocumentFormat, DocumentResult

    doc_intel.read.return_value = DocumentResult(
        success=True,
        operation="read",
        path=path,
        format=DocumentFormat.TXT,
        message="OK",
        data={"text": "", "word_count": 0},
        error=None,
    )
    osm = _make_osm_with_doc_intel(doc_intel)
    result = osm.doc_read(path)
    assert result["verified"] is False


# =========================================================
# 5. OSManager.sheet_* wrappers — end-to-end both directions
# =========================================================


def test_osm_sheet_inspect_positive_verified_true(tmp_path):
    path = str(tmp_path / "data.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
    sheet_intel = MagicMock()
    from genesis_os.spreadsheet_intelligence import SpreadsheetResult

    sheet_intel.inspect.return_value = SpreadsheetResult(
        True, "inspect", path, "OK", {"sheets": 1}, None
    )
    osm = _make_osm_with_sheet_intel(sheet_intel)
    result = osm.sheet_inspect(path)
    assert result["verified"] is True


def test_osm_sheet_inspect_negative_when_file_missing():
    sheet_intel = MagicMock()
    from genesis_os.spreadsheet_intelligence import SpreadsheetResult

    sheet_intel.inspect.return_value = SpreadsheetResult(
        True, "inspect", "/nonexistent/missing.csv", "OK", {}, None
    )
    osm = _make_osm_with_sheet_intel(sheet_intel)
    result = osm.sheet_inspect("/nonexistent/missing.csv")
    assert result["verified"] is False


def test_osm_sheet_sort_negative_when_output_missing(tmp_path):
    out = str(tmp_path / "sorted_missing.csv")  # not created
    sheet_intel = MagicMock()
    from genesis_os.spreadsheet_intelligence import SpreadsheetResult

    sheet_intel.sort.return_value = SpreadsheetResult(
        True, "sort", out, "OK", {"output": out}, None
    )
    osm = _make_osm_with_sheet_intel(sheet_intel)
    result = osm.sheet_sort(out, "a")
    assert result["verified"] is False


# =========================================================
# 6. OSManager.browser_* wrappers — end-to-end both directions
# =========================================================


def test_osm_browser_click_positive_with_postcondition_readback():
    """An explicit click postcondition readback is accepted."""
    browser = MagicMock()
    browser.click.return_value = {
        "success": True,
        "element_found": True,
        "click_postcondition_verified": True,
    }
    osm = _make_osm_with_browser(browser)
    result = osm.browser_click("button#x")
    assert result["verified"] is True


def test_osm_browser_click_negative_no_post_state_signal():
    """When the underlying browser provider only reports
    ``success=True`` (no element_found / verified signal),
    OSManager.browser_click must report ``verified=False``
    honestly.
    """
    browser = MagicMock()
    browser.click.return_value = {"success": True}
    osm = _make_osm_with_browser(browser)
    result = osm.browser_click("button#x")
    assert result["success"] is True
    assert result["verified"] is False
    assert "does not prove" in result.get("verification_reason", "")


def test_osm_browser_extract_negative_empty_text():
    browser = MagicMock()
    browser.extract_text.return_value = {"success": True, "text": ""}
    osm = _make_osm_with_browser(browser)
    result = osm.browser_extract("p")
    assert result["verified"] is False


def test_osm_browser_verify_negative_one_check_failed():
    browser = MagicMock()
    browser.verify_page_state.return_value = {
        "success": True,
        "checks": [
            {"check": "url", "passed": True},
            {"check": "title", "passed": False},
        ],
    }
    osm = _make_osm_with_browser(browser)
    result = osm.browser_verify(expected_url="https://example.com")
    assert result["verified"] is False


def test_osm_browser_screenshot_negative_when_file_missing(tmp_path):
    browser = MagicMock()
    browser.screenshot.return_value = {"success": True, "path": "/nonexistent/shot.png"}
    osm = _make_osm_with_browser(browser)
    result = osm.browser_screenshot("/nonexistent/shot.png")
    assert result["verified"] is False


def test_verify_data_inspect_requires_schema(tmp_path):
    source = tmp_path / "data.json"
    source.write_text('[{"a": 1}]', encoding="utf-8")

    assert verify_data_inspect(True, str(source), {"fields": [{"name": "a"}]})["verified"] is True
    assert verify_data_inspect(True, str(source), {})["verified"] is False


def test_verify_data_transform_rejects_wrong_output(tmp_path):
    source = tmp_path / "data.json"
    output = tmp_path / "out.json"
    source.write_text('[{"a": 1}]', encoding="utf-8")
    output.write_text('[{"a": 2}]', encoding="utf-8")

    result = verify_data_transform(
        True,
        str(output),
        {"output": str(output), "rows": [{"a": 1}]},
    )

    assert result["verified"] is False


# =========================================================
# 7. gui.click / gui.double_click / gui.scroll /
#    gui.keyboard_action — target=None surfaces unresolved_target
# =========================================================


class _FakeGUIProviderNoop:
    """Stand-in for a real GUI provider that records calls but
    does not actually invoke pyautogui. The OSManager's
    ``gui_action`` wrapper invokes ``self.gui.execute`` which in
    turn calls a method named after the action on this fake.
    """

    def __init__(self, *, user32: Optional[_FakeUser32] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._user32 = user32

    def click(self, **kwargs):
        self.calls.append({"op": "click", **kwargs})
        return {"success": True, "data": {}}

    def double_click(self, **kwargs):
        self.calls.append({"op": "double_click", **kwargs})
        return {"success": True, "data": {}}

    def scroll(self, **kwargs):
        self.calls.append({"op": "scroll", **kwargs})
        return {"success": True, "data": {}}

    def keyboard_action(self, **kwargs):
        self.calls.append({"op": "keyboard_action", **kwargs})
        return {"success": True, "data": {}}


class _FakeGUIController:
    """Mirrors ``genesis_os.gui_controller.GUIController``."""

    def __init__(self, provider: _FakeGUIProviderNoop) -> None:
        self._provider = provider

    def execute(self, action, **kwargs):
        method = getattr(self._provider, action.value if hasattr(action, "value") else str(action), None)
        if method is None:
            return {"success": False, "error": "unknown"}
        return method(**kwargs)


class _FakeOSManagerGUI:
    """Minimal stand-in for ``OSManager`` carrying a GUI bridge."""

    def __init__(self, *, user32: Optional[_FakeUser32] = None) -> None:
        self.provider = _FakeGUIProviderNoop(user32=user32)
        if user32 is not None:
            self.provider._user32 = user32
        self.gui = _FakeGUIController(self.provider)

    def gui_action(self, action, **kwargs):
        """Mirror the real ``OSManager.gui_action`` -- dispatch
        through the GUI controller and surface its ``verified``
        flag as the wrapper-level verification signal.
        """
        from genesis_os.gui_controller import GUIAction

        try:
            enum_action = GUIAction(action) if isinstance(action, str) else action
        except ValueError:
            return {"success": False, "error": f"Unknown action: {action}"}
        raw = self.gui.execute(enum_action, **kwargs)
        verified = False
        if isinstance(raw, dict):
            data = raw.get("data") or {}
            if isinstance(data, dict):
                verified = bool(data.get("verified", False))
            if not verified and "verified" in raw:
                verified = bool(raw.get("verified"))
        return {
            "success": raw.get("success", False) if isinstance(raw, dict) else False,
            "operation": f"gui.{action}",
            "data": raw.get("data", {}) if isinstance(raw, dict) else {},
            "verified": verified,
        }


def test_gui_click_target_none_no_focus_returns_unresolved_target():
    """``gui.click`` with ``target=None`` and no safe focused
    window MUST surface ``unresolved_target`` with
    ``verified=False``. This is the contract the
    verification-honesty-sweep directive enforced for the four
    focus-only GUI operations.
    """
    # user32 = None means the resolver cannot observe any
    # foreground window.
    fake_os = _FakeOSManagerGUI(user32=None)
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.click",
        target=None,
        parameters={"x": 100, "y": 200},
        confidence=0.95,
    )
    result = executor.execute(plan)
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    # The provider must NOT have been called -- the resolver
    # refused before dispatch.
    assert not any(c["op"] == "click" for c in fake_os.provider.calls)


def test_gui_double_click_target_none_no_focus_returns_unresolved_target():
    fake_os = _FakeOSManagerGUI(user32=None)
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.double_click",
        target=None,
        parameters={"x": 50, "y": 60},
        confidence=0.95,
    )
    result = executor.execute(plan)
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert not any(c["op"] == "double_click" for c in fake_os.provider.calls)


def test_gui_scroll_target_none_no_focus_returns_unresolved_target():
    fake_os = _FakeOSManagerGUI(user32=None)
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.scroll",
        target=None,
        parameters={"direction": "down", "amount": 3},
        confidence=0.95,
    )
    result = executor.execute(plan)
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert not any(c["op"] == "scroll" for c in fake_os.provider.calls)


def test_gui_keyboard_action_target_none_no_focus_returns_unresolved_target():
    fake_os = _FakeOSManagerGUI(user32=None)
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.keyboard_action",
        target=None,
        parameters={"key": "enter"},
        confidence=0.95,
    )
    result = executor.execute(plan)
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert not any(c["op"] == "keyboard_action" for c in fake_os.provider.calls)


def test_gui_click_target_none_unsafe_console_title_returns_unresolved_target():
    """Even with a foreground window, an unsafe (console /
    REPL) title MUST be refused.
    """
    fake_os = _FakeOSManagerGUI(user32=_FakeUser32(focused_title="Windows PowerShell", focused_hwnd=99))
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.click",
        target=None,
        parameters={"x": 100, "y": 100},
        confidence=0.95,
    )
    result = executor.execute(plan)
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert not any(c["op"] == "click" for c in fake_os.provider.calls)


def test_gui_click_target_none_empty_title_returns_unresolved_target():
    """An empty-title focused window is refused.
    """
    fake_os = _FakeOSManagerGUI(user32=_FakeUser32(focused_title="", focused_hwnd=42))
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.click",
        target=None,
        parameters={"x": 100, "y": 100},
        confidence=0.95,
    )
    result = executor.execute(plan)
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert not any(c["op"] == "click" for c in fake_os.provider.calls)


def test_gui_click_target_none_safe_window_dispatches_without_focus_verification():
    """A safe window permits dispatch, but focus is not a click postcondition."""
    fake_os = _FakeOSManagerGUI(user32=_FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345))
    executor = ActionExecutor(os_manager=fake_os)
    plan = ActionPlan(
        operation="gui.click",
        target=None,
        parameters={"x": 200, "y": 300},
        confidence=0.95,
    )
    result = executor.execute(plan)
    # The dispatch actually happened.
    click_calls = [c for c in fake_os.provider.calls if c["op"] == "click"]
    assert len(click_calls) == 1
    assert result.success is True
    assert result.verified is False
    assert result.status in {"success", "verification_failed", "verification_unavailable"}