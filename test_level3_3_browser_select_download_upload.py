"""
Genesis OS — Level 3.3
Browser Select / Download / Upload Tests.

Tests the newly added browser capabilities:
    - select (dropdown selection by value, label, index)
    - download (file download from URL)
    - upload (file upload to input element)

Each provider (base, selenium, playwright) is tested independently.
Adversarial edge cases are covered.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from genesis_os.browser_manager import (
    BrowserManager,
    BrowserSession,
    BrowserProvider,
    WebBrowserProvider,
)

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: constructs a real BrowserManager and OSManager.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


# =========================================================
# HELPERS
# =========================================================


class MockProvider(BrowserProvider):
    """Mock provider that records calls and returns configurable results."""

    name = "mock"
    available = True

    def __init__(self):
        self.calls = []
        self._select_result = {"success": True, "operation": "browser.select"}
        self._download_result = {"success": True, "operation": "browser.download"}
        self._upload_result = {"success": True, "operation": "browser.upload"}

    def open_url(self, url):
        return {"success": True, "operation": "browser.open_url", "url": url}

    def navigate(self, url):
        return self.open_url(url)

    def search(self, query, engine="google"):
        return {"success": True, "operation": "browser.search", "query": query}

    def select(self, selector, value=None, label=None, index=None):
        self.calls.append(("select", selector, value, label, index))
        return self._select_result

    def download(self, url, save_path=None):
        self.calls.append(("download", url, save_path))
        return self._download_result

    def upload(self, selector, file_path):
        self.calls.append(("upload", selector, file_path))
        return self._upload_result


# =========================================================
# BASE PROVIDER — DEFAULT UNSUPPORTED
# =========================================================


class TestBrowserProviderBaseDefaults:
    """Base BrowserProvider returns unsupported for select/download/upload."""

    def test_select_returns_unsupported(self):
        provider = WebBrowserProvider()
        result = provider.select("select#dropdown")
        assert result["success"] is False
        assert "does not support select" in result["error"]

    def test_download_returns_unsupported(self):
        provider = WebBrowserProvider()
        result = provider.download("https://example.com/file.txt")
        assert result["success"] is False
        assert "does not support download" in result["error"]

    def test_upload_returns_unsupported(self):
        provider = WebBrowserProvider()
        result = provider.upload("input[type=file]", "/tmp/test.txt")
        assert result["success"] is False
        assert "does not support upload" in result["error"]


# =========================================================
# MOCK PROVIDER — DELEGATION
# =========================================================


class TestMockProviderSelect:
    def test_select_by_value(self):
        p = MockProvider()
        result = p.select("select#lang", value="python")
        assert result["success"] is True
        assert p.calls[-1] == ("select", "select#lang", "python", None, None)

    def test_select_by_label(self):
        p = MockProvider()
        result = p.select("select#lang", label="Python")
        assert result["success"] is True
        assert p.calls[-1] == ("select", "select#lang", None, "Python", None)

    def test_select_by_index(self):
        p = MockProvider()
        result = p.select("select#lang", index=2)
        assert result["success"] is True
        assert p.calls[-1] == ("select", "select#lang", None, None, 2)

    def test_select_no_method_returns_error(self):
        p = MockProvider()
        p._select_result = {"success": False, "error": "No selection method specified"}
        result = p.select("select#lang")
        assert result["success"] is False


class TestMockProviderDownload:
    def test_download_delegates(self):
        p = MockProvider()
        result = p.download("https://example.com/file.zip", save_path="/tmp/file.zip")
        assert result["success"] is True
        assert p.calls[-1] == ("download", "https://example.com/file.zip", "/tmp/file.zip")

    def test_download_no_save_path(self):
        p = MockProvider()
        result = p.download("https://example.com/file.zip")
        assert result["success"] is True
        assert p.calls[-1] == ("download", "https://example.com/file.zip", None)


class TestMockProviderUpload:
    def test_upload_delegates(self):
        p = MockProvider()
        result = p.upload("input[type=file]", "/tmp/upload.txt")
        assert result["success"] is True
        assert p.calls[-1] == ("upload", "input[type=file]", "/tmp/upload.txt")


# =========================================================
# BROWSER MANAGER DELEGATION
# =========================================================


class TestBrowserManagerSelect:
    def _make_sessioned_mgr(self, session_id="default"):
        mgr = BrowserManager()
        mock = MockProvider()
        mgr._sessions[session_id] = BrowserSession(provider=mock)
        mgr._providers = [mock]
        return mgr, mock

    def test_select_delegates_to_provider(self):
        mgr, mock = self._make_sessioned_mgr()
        result = mgr.select("select#fruit", value="apple")
        assert result["success"] is True
        assert mock.calls[-1][0] == "select"

    def test_select_with_label(self):
        mgr, mock = self._make_sessioned_mgr()
        result = mgr.select("select#fruit", label="Apple")
        assert result["success"] is True

    def test_select_with_index(self):
        mgr, mock = self._make_sessioned_mgr()
        result = mgr.select("select#fruit", index=0)
        assert result["success"] is True

    def test_select_custom_session(self):
        mgr, mock = self._make_sessioned_mgr("custom")
        result = mgr.select("select#fruit", value="x", session_id="custom")
        assert result["success"] is True


class TestBrowserManagerDownload:
    def _make_sessioned_mgr(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mgr._sessions["default"] = BrowserSession(provider=mock)
        mgr._providers = [mock]
        return mgr, mock

    def test_download_delegates_to_provider(self):
        mgr, mock = self._make_sessioned_mgr()
        result = mgr.download("https://example.com/f.zip")
        assert result["success"] is True
        assert mock.calls[-1][0] == "download"

    def test_download_with_save_path(self):
        mgr, mock = self._make_sessioned_mgr()
        result = mgr.download("https://example.com/f.zip", save_path="/tmp/f.zip")
        assert result["success"] is True
        assert mock.calls[-1] == ("download", "https://example.com/f.zip", "/tmp/f.zip")


class TestBrowserManagerUpload:
    def test_upload_delegates_to_provider(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mgr._sessions["default"] = BrowserSession(provider=mock)
        mgr._providers = [mock]
        result = mgr.upload("input[type=file]", "/tmp/doc.pdf")
        assert result["success"] is True
        assert mock.calls[-1] == ("upload", "input[type=file]", "/tmp/doc.pdf")


# =========================================================
# OS MANAGER WIRING
# =========================================================


class TestOSManagerBrowserSelect:
    def test_browser_select_reaches_os_manager(self):
        from genesis_os.os_manager import OSManager

        os_mgr = OSManager()
        mock = MockProvider()
        os_mgr.browser._sessions["default"] = BrowserSession(provider=mock)
        os_mgr.browser._providers = [mock]
        result = os_mgr.browser_select("select#x", value="y")
        assert result["success"] is True

    def test_browser_download_reaches_os_manager(self):
        from genesis_os.os_manager import OSManager

        os_mgr = OSManager()
        mock = MockProvider()
        os_mgr.browser._sessions["default"] = BrowserSession(provider=mock)
        os_mgr.browser._providers = [mock]
        result = os_mgr.browser_download("https://example.com/f.zip")
        assert result["success"] is True

    def test_browser_upload_reaches_os_manager(self):
        from genesis_os.os_manager import OSManager

        os_mgr = OSManager()
        mock = MockProvider()
        os_mgr.browser._sessions["default"] = BrowserSession(provider=mock)
        os_mgr.browser._providers = [mock]
        result = os_mgr.browser_upload("input[type=file]", "/tmp/x.txt")
        assert result["success"] is True


# =========================================================
# ACTION EXECUTOR DISPATCH
# =========================================================


class TestActionExecutorBrowserSelect:
    def test_browser_select_dispatched(self):
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        os_mgr.browser_select.return_value = {"success": True, "operation": "browser.select"}
        executor = ActionExecutor(os_mgr)

        plan = ActionPlan(
            operation="browser.select",
            target="select#color",
            parameters={"value": "red"},
            confidence=0.95,
        )
        result = executor.execute(plan)
        assert result.success is True
        os_mgr.browser_select.assert_called_once()

    def test_browser_select_by_label_dispatched(self):
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        os_mgr.browser_select.return_value = {"success": True, "operation": "browser.select"}
        executor = ActionExecutor(os_mgr)

        plan = ActionPlan(
            operation="browser.select",
            target="select#color",
            parameters={"label": "Red"},
            confidence=0.95,
        )
        result = executor.execute(plan)
        assert result.success is True

    def test_browser_select_by_index_dispatched(self):
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        os_mgr.browser_select.return_value = {"success": True, "operation": "browser.select"}
        executor = ActionExecutor(os_mgr)

        plan = ActionPlan(
            operation="browser.select",
            target="select#color",
            parameters={"index": 1},
            confidence=0.95,
        )
        result = executor.execute(plan)
        assert result.success is True


class TestActionExecutorBrowserDownload:
    def test_browser_download_dispatched(self, workspace_root):
        """RECLASSIFIED 2026-10-07 under the F5 blast-radius model.

        This test previously asserted that browser.download is
        confirmation-gated, on the authority of security_model declaring
        it MEDIUM/MODIFYING. That is no longer the gating source of
        truth. Blast radius classifies browser.download as Tier 2
        (reversible_local) by explicit product decision: a download is
        INBOUND, creates a local file, and deleting that file reverses
        it. Nothing is transmitted outward, which is what separates it
        from browser.upload.

        So the old expectation is now inverted, deliberately: an
        unconfirmed download executes. The residual risk is
        confidentiality, not reversibility, and blast radius does not
        model confidentiality -- that gap is recorded separately.

        Retargeted 2026-10-08 for the workspace boundary: the save path
        now has to be inside the configured root. `target` is a URL and
        is deliberately NOT scanned -- only `save_path` is a path.
        """
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        save = workspace_root / "f.zip"
        os_mgr.browser_download.return_value = {"success": True, "operation": "browser.download", "save_path": str(save)}
        executor = ActionExecutor(os_mgr)

        ungated = ActionPlan(
            operation="browser.download",
            target="https://example.com/f.zip",
            parameters={"save_path": str(save)},
            confidence=0.95,
        )
        result = executor.execute(ungated)
        assert result.status != "confirmation_required"
        os_mgr.browser_download.assert_called_once()

    def test_browser_download_outside_the_workspace_requires_a_grant(self, tmp_path):
        """Bucket (b) counterpart for the download test above.

        Same download, same inbound/reversible reasoning, but writing
        outside the root: gated without a grant, dispatched with one.
        Without this pair the retargeted test would pass whether or not
        the boundary worked.
        """
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan, attach_authorization
        from genesis_os.approval_store import ApprovalStore
        from genesis_os.authorization_grant import issue_authorization_grant

        os_mgr = MagicMock()
        save = tmp_path / "f.zip"
        os_mgr.browser_download.return_value = {
            "success": True, "operation": "browser.download",
            "save_path": str(save),
        }
        plan = ActionPlan(
            operation="browser.download",
            target="https://example.com/f.zip",
            parameters={"save_path": str(save)},
            confidence=0.95,
        )
        result = ActionExecutor(os_mgr).execute(plan)
        assert result.status == "confirmation_required"
        assert result.executed is False
        os_mgr.browser_download.assert_not_called()

        # The grant must cover the WHOLE plan, not just the escalated
        # argument: `target` is a URL here (correctly not scanned by the
        # boundary), but it is still part of what the human approved.
        args = {"save_path": str(save), "target": "https://example.com/f.zip"}
        token = ApprovalStore.issue_token("browser.download", args)
        ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
        granted = attach_authorization(
            plan, issue_authorization_grant(
                operation="browser.download", arguments=args, token=token,
            ), arguments=args,
        )
        result2 = ActionExecutor(os_mgr).execute(granted)
        assert result2.status != "confirmation_required"
        os_mgr.browser_download.assert_called_once()


class TestActionExecutorBrowserUpload:
    def test_browser_upload_dispatched(self):
        """UPDATED 2026-10-04, same shape as the download case:
        `security_model.py` declares `browser.upload` with
        `requires_confirmation=True` ("Uploads a local file to a remote
        web form"), and the Phase 2 semantic adapter additionally placed
        it in `APPROVAL_REQUIRED_CAPABILITIES`
        (`PHASE_2_SEMANTIC_ADAPTER_2026-09-26.md:77,109`). The gate
        refuses the unconfirmed plan; the confirmed plan dispatches.
        """
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        os_mgr.browser_upload.return_value = {"success": True, "operation": "browser.upload"}
        executor = ActionExecutor(os_mgr)

        blocked = ActionPlan(
            operation="browser.upload",
            target="input[type=file]",
            parameters={"file_path": "/tmp/doc.pdf"},
            confidence=0.95,
        )
        blocked_result = executor.execute(blocked)
        assert blocked_result.success is False
        assert blocked_result.status == "confirmation_required"
        os_mgr.browser_upload.assert_not_called()

        plan = ActionPlan(
            operation="browser.upload",
            target="input[type=file]",
            parameters={"file_path": "/tmp/doc.pdf", "confirmed": True},
            confidence=0.95,
        )
        # Tier 1 capability: `confirmed: True` is no longer sufficient.
        # It travelled inside `parameters`, which is model-controlled
        # JSON, so the executor requires an AuthorizationGrant minted
        # from a real argument-bound single-use approval. This half of
        # the test now proves that forgeable channel does NOT open the
        # gate; the grant path is covered by the Step 1b battery.
        result = executor.execute(plan)
        assert result.success is False
        assert result.status == "confirmation_required"
        os_mgr.browser_upload.assert_not_called()

        # And the grant path does dispatch.
        from genesis_os.action_plan import attach_authorization
        from genesis_os.approval_store import ApprovalStore
        from genesis_os.authorization_grant import issue_authorization_grant

        token = ApprovalStore.issue_token(
            "browser.upload",
            {"selector": "input[type=file]", "file_path": "/tmp/doc.pdf"},
        )
        ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
        grant = issue_authorization_grant(
            operation="browser.upload",
            arguments={
                "selector": "input[type=file]",
                "file_path": "/tmp/doc.pdf",
            },
            token=token,
        )
        granted = attach_authorization(
            ActionPlan(
                operation="browser.upload",
                target="input[type=file]",
                parameters={
                    "selector": "input[type=file]",
                    "file_path": "/tmp/doc.pdf",
                },
                confidence=0.95,
            ),
            grant,
            arguments={
                "selector": "input[type=file]",
                "file_path": "/tmp/doc.pdf",
            },
        )
        result = executor.execute(granted)
        assert result.success is True
        os_mgr.browser_upload.assert_called_once()


# =========================================================
# CAPABILITY REGISTRY
# =========================================================


class TestCapabilityRegistryBrowserOperations:
    def test_browser_select_registered(self):
        from genesis_os.capability_registry import CapabilityRegistry

        assert CapabilityRegistry.exists("browser.select")

    def test_browser_download_registered(self):
        from genesis_os.capability_registry import CapabilityRegistry

        assert CapabilityRegistry.exists("browser.download")

    def test_browser_upload_registered(self):
        from genesis_os.capability_registry import CapabilityRegistry

        assert CapabilityRegistry.exists("browser.upload")


# =========================================================
# ADVERSARIAL — EDGE CASES
# =========================================================


class TestBrowserSelectAdversarial:
    def test_select_with_empty_selector(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mock._select_result = {"success": False, "error": "Selector required"}
        mgr._sessions["default"] = BrowserSession(provider=mock)
        result = mgr.select("", value="x")
        assert result["success"] is False

    def test_select_with_no_method(self):
        p = MockProvider()
        p._select_result = {"success": False, "error": "No selection method specified"}
        result = p.select("select#x")
        assert result["success"] is False

    def test_select_all_methods_none(self):
        p = MockProvider()
        result = p.select("select#x", value=None, label=None, index=None)
        assert p.calls[-1] == ("select", "select#x", None, None, None)


class TestBrowserDownloadAdversarial:
    def test_download_invalid_url(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mock._download_result = {"success": False, "error": "Invalid URL"}
        mgr._sessions["default"] = BrowserSession(provider=mock)
        result = mgr.download("not-a-url")
        assert result["success"] is False

    def test_download_network_failure(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mock._download_result = {"success": False, "error": "Connection refused"}
        mgr._sessions["default"] = BrowserSession(provider=mock)
        result = mgr.download("https://nonexistent.example.com/file.zip")
        assert result["success"] is False


class TestBrowserUploadAdversarial:
    def test_upload_missing_file(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mock._upload_result = {"success": False, "error": "File not found"}
        mgr._sessions["default"] = BrowserSession(provider=mock)
        result = mgr.upload("input[type=file]", "/nonexistent/file.txt")
        assert result["success"] is False

    def test_upload_no_selector(self):
        mgr = BrowserManager()
        mock = MockProvider()
        mock._upload_result = {"success": False, "error": "No file input found"}
        mgr._sessions["default"] = BrowserSession(provider=mock)
        result = mgr.upload("", "/tmp/file.txt")
        assert result["success"] is False
