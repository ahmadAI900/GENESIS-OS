"""
Genesis OS — Level 3 Browser Closed-Loop Verification Tests.

Tests the INTENT → ACTION → PAGE STATE → OBSERVATION → VERIFICATION pipeline
for browser operations via the ObservationLoop.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.observation_loop import ObservationLoop, ObservationResult


# =========================================================
# HELPERS
# =========================================================


def _mock_os_manager():
    """Create a mock OSManager with browser verification."""
    mgr = MagicMock()
    mgr.browser_get_url.return_value = {"success": True, "url": "https://example.com"}
    mgr.browser_get_title.return_value = {"success": True, "title": "Example Page"}
    mgr.browser_verify.return_value = {"success": True}
    mgr.browser_find.return_value = {"success": True, "count": 1}
    mgr.browser_extract.return_value = {"success": True, "text": "Welcome"}
    mgr.inspect_application.return_value = {"running": True}
    mgr.inspect_file.return_value = {"exists": True}
    mgr.inspect_folder.return_value = {"exists": True}
    return mgr


def _make_result(operation, success=True, executed=True, verified=True):
    """Create a mock ActionResult."""
    return ActionResult(
        success=success,
        operation=operation,
        target=None,
        application=None,
        status="success" if success else "failed",
        message="ok",
        executed=executed,
        verified=verified,
    )


# =========================================================
# BROWSER OPEN_URL OBSERVATION
# =========================================================


class TestBrowserOpenUrlObservation:
    def test_observe_browser_open_url(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(operation="browser.open_url", target="https://example.com")
        result = _make_result("browser.open_url")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is True

    def test_observe_browser_search(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.search",
            target="python tutorial",
            parameters={"query": "python tutorial", "engine": "google"},
        )
        result = _make_result("browser.search")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is True


# =========================================================
# BROWSER CLICK OBSERVATION
# =========================================================


class TestBrowserClickObservation:
    def test_observe_browser_click(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(operation="browser.click", target="button#submit")
        result = _make_result("browser.click")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert observation.actual_state.get("click_performed") is False
        assert observation.actual_state.get("browser_verified") is True

    def test_observe_browser_click_with_session(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.click",
            target="button#submit",
            parameters={"session_id": "custom"},
        )
        result = _make_result("browser.click")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert observation.actual_state.get("browser_session") == "custom"


# =========================================================
# BROWSER TYPE OBSERVATION
# =========================================================


class TestBrowserTypeObservation:
    def test_observe_browser_type(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.type",
            target="input#search",
            parameters={"text": "hello world"},
        )
        result = _make_result("browser.type")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert observation.actual_state.get("type_performed") is False
        assert observation.actual_state.get("type_observation")


# =========================================================
# BROWSER SCROLL OBSERVATION
# =========================================================


class TestBrowserScrollObservation:
    def test_observe_browser_scroll(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.scroll",
            target=None,
            parameters={"direction": "down", "amount": 5},
        )
        result = _make_result("browser.scroll")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False


# =========================================================
# BROWSER SELECT OBSERVATION
# =========================================================


class TestBrowserSelectObservation:
    def test_observe_browser_select_by_value(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.select",
            target="select#color",
            parameters={"value": "red"},
        )
        result = _make_result("browser.select")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert observation.actual_state.get("select_performed") is False
        assert observation.actual_state.get("select_value") is None

    def test_observe_browser_select_by_label(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.select",
            target="select#color",
            parameters={"label": "Red"},
        )
        result = _make_result("browser.select")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert observation.actual_state.get("select_observation")

    def test_observe_browser_select_by_index(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.select",
            target="select#color",
            parameters={"index": 2},
        )
        result = _make_result("browser.select")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert observation.actual_state.get("select_observation")


# =========================================================
# BROWSER DOWNLOAD OBSERVATION
# =========================================================


class TestBrowserDownloadObservation:
    def test_observe_browser_download_file_not_found(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.download",
            target="https://example.com/file.zip",
            parameters={"save_path": "/tmp/file.zip"},
        )
        result = _make_result("browser.download")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert "Download completion was not independently observed" in (observation.discrepancy or "")

    def test_observe_browser_download_file_exists(self):
        import tempfile, os
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as f:
            tmp_path = f.name
        try:
            plan = ActionPlan(
                operation="browser.download",
                target="https://example.com/file.zip",
                parameters={"save_path": tmp_path},
            )
            result = _make_result("browser.download")
            observation = loop.observe("step-1", plan, result)
            assert observation.actual_state.get("download_file_exists") is True
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# =========================================================
# BROWSER UPLOAD OBSERVATION
# =========================================================


class TestBrowserUploadObservation:
    def test_observe_browser_upload_source_exists(self):
        import tempfile, os
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            tmp_path = f.name
        try:
            plan = ActionPlan(
                operation="browser.upload",
                target="input[type=file]",
                parameters={"file_path": tmp_path},
            )
            result = _make_result("browser.upload")
            observation = loop.observe("step-1", plan, result)
            assert observation.actual_state.get("upload_source_exists") is True
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_observe_browser_upload_missing_source(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(
            operation="browser.upload",
            target="input[type=file]",
            parameters={"file_path": "/nonexistent/file.pdf"},
        )
        result = _make_result("browser.upload")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is False
        assert "Upload completion was not independently observed" in (observation.discrepancy or "")


# =========================================================
# BROWSER FIND / EXTRACT OBSERVATION
# =========================================================


class TestBrowserFindObservation:
    def test_observe_browser_find(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(operation="browser.find", target="Welcome")
        result = _make_result("browser.find")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is True


class TestBrowserExtractObservation:
    def test_observe_browser_extract(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(operation="browser.extract", target="div.content")
        result = _make_result("browser.extract")
        observation = loop.observe("step-1", plan, result)
        assert observation.matches_expected is True


# =========================================================
# CAPABILITY OBSERVER REGISTRATION
# =========================================================


class TestCapabilityObserverBrowserOperations:
    def test_click_observer_registered(self):
        mgr = _mock_os_manager()
        from genesis_os.observation_loop import CapabilityObserver
        observer = CapabilityObserver(mgr)
        plan = ActionPlan(operation="browser.click", target="button")
        result = observer.observe(plan)
        assert "click_performed" in result

    def test_type_observer_registered(self):
        mgr = _mock_os_manager()
        from genesis_os.observation_loop import CapabilityObserver
        observer = CapabilityObserver(mgr)
        plan = ActionPlan(operation="browser.type", target="input", parameters={"text": "x"})
        result = observer.observe(plan)
        assert "type_performed" in result

    def test_scroll_observer_registered(self):
        mgr = _mock_os_manager()
        from genesis_os.observation_loop import CapabilityObserver
        observer = CapabilityObserver(mgr)
        plan = ActionPlan(operation="browser.scroll", parameters={"direction": "up"})
        result = observer.observe(plan)
        assert "scroll_performed" in result

    def test_select_observer_registered(self):
        mgr = _mock_os_manager()
        from genesis_os.observation_loop import CapabilityObserver
        observer = CapabilityObserver(mgr)
        plan = ActionPlan(operation="browser.select", target="select#x", parameters={"value": "y"})
        result = observer.observe(plan)
        assert "select_performed" in result

    def test_download_observer_registered(self):
        mgr = _mock_os_manager()
        from genesis_os.observation_loop import CapabilityObserver
        observer = CapabilityObserver(mgr)
        plan = ActionPlan(operation="browser.download", target="https://x.com/f.zip")
        result = observer.observe(plan)
        assert "download_performed" in result

    def test_upload_observer_registered(self):
        mgr = _mock_os_manager()
        from genesis_os.observation_loop import CapabilityObserver
        observer = CapabilityObserver(mgr)
        plan = ActionPlan(operation="browser.upload", target="input[type=file]", parameters={"file_path": "/f"})
        result = observer.observe(plan)
        assert "upload_performed" in result


# =========================================================
# CLOSED-LOOP INTEGRATION
# =========================================================


class TestBrowserClosedLoopIntegration:
    def test_full_loop_click(self):
        """INTENT → ACTION → PAGE STATE → OBSERVATION → VERIFICATION"""
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)

        # INTENT
        plan = ActionPlan(operation="browser.click", target="button#login")

        # ACTION (simulated)
        action_result = _make_result("browser.click", success=True, verified=True)

        # OBSERVATION
        observation = loop.observe("step-login", plan, action_result)

        # VERIFICATION
        assert observation.matches_expected is False
        assert observation.step_id == "step-login"
        assert observation.operation == "browser.click"
        assert observation.discrepancy

    def test_full_loop_select(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)

        plan = ActionPlan(
            operation="browser.select",
            target="select#country",
            parameters={"label": "United States"},
        )
        action_result = _make_result("browser.select")
        observation = loop.observe("step-country", plan, action_result)

        assert observation.matches_expected is False
        assert observation.actual_state.get("select_performed") is False

    def test_full_loop_type_and_verify(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)

        plan = ActionPlan(
            operation="browser.type",
            target="input#email",
            parameters={"text": "user@example.com"},
        )
        action_result = _make_result("browser.type")
        observation = loop.observe("step-email", plan, action_result)

        assert observation.matches_expected is False
        assert observation.actual_state.get("type_performed") is False

    def test_observation_result_to_dict(self):
        mgr = _mock_os_manager()
        loop = ObservationLoop(mgr)
        plan = ActionPlan(operation="browser.click", target="button")
        result = _make_result("browser.click")
        observation = loop.observe("step-1", plan, result)
        d = observation.to_dict()
        assert "step_id" in d
        assert "expected_state" in d
        assert "actual_state" in d
        assert "matches_expected" in d


# =========================================================
# BROWSER CLICK RISK ESCALATION AT THE AUTHORIZATION GATE
# =========================================================
#
# The executor can read the target element's accessible text (or learn
# that there is none). `blast_radius.browser_click_escalation` uses that
# to escalate an irreversible-looking click to Tier 1. Before 2026-10-15
# the executor built that context and then called `assess_operation_risk`
# with it, but never forwarded the context to the gate -- so the
# escalation was computed and discarded, and a click on "Confirm purchase"
# dispatched as Tier 2.
#
# Both cases below FAIL before that fix and PASS after it. The benign
# case pins the other direction: a readable, ordinary link must stay
# Tier 2 and still dispatch.


class _CountingBrowser:
    """Records dispatches so a blocked click can be proven not to run."""

    def __init__(self, element_text=None, no_text=False):
        self.clicks = 0
        self._element_text = element_text
        self._no_text = no_text

    def extract_text(self, selector, session_id="default"):
        if self._no_text:
            # An element that exposes no readable text (icon/image button).
            return {"success": True, "text": ""}
        return {"success": True, "text": self._element_text or ""}

    def _get_page(self):
        raise AttributeError("no page handle in this test double")

    def browser_click(self, selector, session_id="default"):
        self.clicks += 1
        return {
            "success": True, "operation": "browser.click",
            "executed": True, "verified": True,
        }


def _click_executor(browser):
    """An ActionExecutor whose OS layer dispatches browser.click."""
    mgr = MagicMock()
    mgr.browser = browser
    mgr.browser_click.side_effect = browser.browser_click
    from genesis_os.action_executor import ActionExecutor
    return ActionExecutor(mgr), mgr


def _click_plan():
    return ActionPlan(
        operation="browser.click",
        target="#confirm-order",
        parameters={"selector": "#confirm-order"},
        capability_id="browser.click",
    )


class TestBrowserClickRiskEscalationAtGate:
    def test_high_risk_signal_text_is_gated_and_never_dispatched(self):
        browser = _CountingBrowser(element_text="Confirm purchase")
        executor, _mgr = _click_executor(browser)

        result = executor.execute(_click_plan())

        assert result.status == "confirmation_required", (
            "a click whose accessible text carries a high-risk signal must "
            f"require a grant, got status={result.status!r} "
            f"message={result.message!r}"
        )
        assert browser.clicks == 0, (
            f"the gated click was dispatched {browser.clicks} time(s); the "
            "gate must block before any dispatch"
        )

    def test_unassessable_no_text_element_is_gated_and_never_dispatched(self):
        browser = _CountingBrowser(no_text=True)
        executor, _mgr = _click_executor(browser)

        result = executor.execute(_click_plan())

        assert result.status == "confirmation_required", (
            "an element Genesis cannot read is unknown risk, not assumed "
            f"harmless; got status={result.status!r}"
        )
        assert browser.clicks == 0, (
            f"the unassessable click was dispatched {browser.clicks} time(s)"
        )

    def test_benign_readable_link_stays_tier2_and_dispatches(self):
        browser = _CountingBrowser(element_text="Read more about pricing")
        executor, _mgr = _click_executor(browser)

        result = executor.execute(_click_plan())

        assert result.status != "confirmation_required", (
            "an ordinary readable link must NOT be escalated; got "
            f"status={result.status!r}"
        )
        assert browser.clicks == 1, (
            "the benign click must still dispatch exactly once, got "
            f"{browser.clicks}"
        )
