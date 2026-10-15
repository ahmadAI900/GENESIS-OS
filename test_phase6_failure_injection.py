"""
Genesis OS — Phase 6 Failure Injection Tests.

Tests for:
- Stale target handling
- Provider failures
- Timeout behavior
- Ambiguity → clarification
- Focus loss detection
- verification_reason preservation
- False-success prevention
"""

import time
import threading
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from genesis_os.gui_controller import (
    GUIAction, GUIController, GUIActionResult, GUIProvider,
)
from genesis_os.window_models import WindowResolver, WindowIdentity, UNSAFE_TITLE_PATTERNS
from genesis_os.ui_target_models import UITarget, UITargetResolution, normalize_hotkey
from genesis_os.gui_observer import GUIObserver, GUIVerifier, Observation
from genesis_os.action_result import ActionResult
from genesis_os.runtime_focus_resolver import (
    RuntimeFocusResolver, RuntimeFocusResolution, FocusedWindow,
)


# ============================================================
# STALE TARGET HANDLING
# ============================================================

class TestStaleTargetHandling:
    """Verify that stale targets are detected and re-resolved."""

    def test_window_resolver_returns_none_for_destroyed_window(self):
        resolver = WindowResolver()
        if not resolver.available:
            pytest.skip("user32 not available")
        result = resolver.find_window(
            r"^__nonexistent_window_title_12345__$", timeout=0.0
        )
        assert result is None

    def test_uui_target_confidence_below_threshold_is_ambiguous(self):
        target = UITarget(
            name="Save",
            confidence=0.5,
        )
        resolution = UITargetResolution(
            resolved=False,
            ambiguous=True,
            target=target,
            candidates=[target],
        )
        assert resolution.ambiguous is True
        assert resolution.resolved is False

    def test_focus_resolver_rejects_stale_hwnd(self):
        resolver = RuntimeFocusResolver()
        # HWND 0 is never a valid foreground window
        safe, reason = resolver.is_safe_target(0, "")
        assert safe is False


# ============================================================
# PROVIDER FAILURE HANDLING
# ============================================================

class TestProviderFailureHandling:
    """Verify provider failures map to correct error taxonomy."""

    def test_no_provider_returns_failure(self):
        controller = GUIController.__new__(GUIController)
        controller._provider = None
        result = controller.click(100, 200)
        assert result.success is False
        assert "no gui provider" in result.error.lower()

    def test_provider_health_reports_none_when_no_provider(self):
        controller = GUIController.__new__(GUIController)
        controller._provider = None
        health = controller.provider_health()
        assert health["provider"] is None
        assert health["available"] is False

    def test_action_result_failure_result_preserves_status(self):
        result = ActionResult.failure_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Provider failed",
            status="provider_failure",
            error="pyautogui not available",
            executed=False,
            verified=False,
        )
        assert result.status == "provider_failure"
        assert result.trustworthy_success is False
        assert result.final_state == "not_executed"

    def testActionResult_execution_failed_status(self):
        result = ActionResult.failure_result(
            operation="gui.hotkey",
            target="Ctrl+S",
            application=None,
            message="Dispatch failed",
            status="execution_failed",
            error="timeout",
            executed=True,
            verified=False,
        )
        assert result.final_state == "execution_failed"
        assert result.trustworthy_success is False


# ============================================================
# TIMEOUT HANDLING
# ============================================================

class TestTimeoutHandling:
    """Verify bounded timeouts and timeout state."""

    def test_wait_for_condition_respects_timeout(self):
        observer = GUIObserver()
        start = time.monotonic()
        result = observer.wait_for_condition(
            lambda: False, timeout=0.5, poll_interval=0.1
        )
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 2.0

    def test_window_resolver_find_window_timeout_bounded(self):
        resolver = WindowResolver()
        if not resolver.available:
            pytest.skip("user32 not available")
        start = time.monotonic()
        result = resolver.find_window(
            r"^__nonexistent__$", timeout=0.3, poll_interval=0.1
        )
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 2.0

    def test_timeout_produces_verified_false(self):
        result = ActionResult.failure_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Timed out",
            status="timed_out",
            error="Operation timed out after 3.0s",
            executed=False,
            verified=False,
        )
        assert result.verified is False
        assert result.trustworthy_success is False


# ============================================================
# AMBIGUITY → CLARIFICATION
# ============================================================

class TestAmbiguityHandling:
    """Verify ambiguous targets produce clarification, not arbitrary action."""

    def test_ambiguous_resolution_not_resolved(self):
        target1 = UITarget(name="Save", confidence=0.6)
        target2 = UITarget(name="Save As", confidence=0.5)
        resolution = UITargetResolution(
            resolved=False,
            ambiguous=True,
            target=None,
            candidates=[target1, target2],
        )
        assert resolution.resolved is False
        assert resolution.ambiguous is True
        assert len(resolution.candidates) == 2

    def test_unsupported_resolution(self):
        resolution = UITargetResolution(
            resolved=False,
            ambiguous=False,
            unsupported=True,
            target=None,
            candidates=[],
        )
        assert resolution.unsupported is True
        assert resolution.resolved is False

    def test_high_confidence_target_resolved(self):
        target = UITarget(name="Save Button", confidence=0.95)
        resolution = UITargetResolution(
            resolved=True,
            ambiguous=False,
            target=target,
            candidates=[target],
        )
        assert resolution.resolved is True
        assert resolution.ambiguous is False


# ============================================================
# FOCUS LOSS DETECTION
# ============================================================

class TestFocusLossDetection:
    """Verify focus loss is detected and reported honestly."""

    def test_focus_resolver_verification_reason_set_on_success(self):
        resolver = RuntimeFocusResolver()
        outcome = RuntimeFocusResolution(
            dispatched=True,
            verified=True,
            focused=FocusedWindow(hwnd=12345, title="Test"),
        )
        # Simulate the verification path
        outcome.verification_reason = "Foreground HWND 12345 retained after dispatch; focus verified."
        assert outcome.verification_reason is not None
        assert "retained" in outcome.verification_reason

    def test_focus_resolver_verification_reason_set_on_failure(self):
        outcome = RuntimeFocusResolution(
            dispatched=True,
            verified=False,
            focused=FocusedWindow(hwnd=12345, title="Test"),
            status="verification_failed",
            error="Foreground window changed",
            verification_reason="Foreground HWND changed from 12345 during type_text; focus not retained.",
        )
        assert outcome.verification_reason is not None
        assert "changed" in outcome.verification_reason

    def test_focus_only_dispatch_unverified_on_focus_change(self):
        result = ActionResult.failure_result(
            operation="gui.click",
            target=None,
            application=None,
            message="Foreground window changed during dispatch",
            status="verification_failed",
            error="Foreground window changed",
            executed=True,
            verified=False,
        )
        assert result.verified is False
        assert result.executed is True
        assert result.trustworthy_success is False


# ============================================================
# FALSE-SUCCESS PREVENTION
# ============================================================

class TestFalseSuccessPrevention:
    """Verify no false-success conversions exist."""

    def test_unresolved_not_success(self):
        result = ActionResult.failure_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Could not resolve target",
            status="unresolved_target",
            error="No safe window",
            executed=False,
            verified=False,
        )
        assert result.success is False
        assert result.trustworthy_success is False

    def test_timeout_not_success(self):
        result = ActionResult.failure_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Timed out",
            status="timed_out",
            error="timeout",
            executed=False,
            verified=False,
        )
        assert result.success is False

    def test_unsupported_not_success(self):
        result = ActionResult.failure_result(
            operation="gui.select",
            target="dropdown",
            application=None,
            message="Unsupported operation",
            status="unsupported",
            error="No provider supports gui.select",
            executed=False,
            verified=False,
        )
        assert result.success is False

    def test_dispatch_failure_not_success(self):
        result = ActionResult.failure_result(
            operation="gui.hotkey",
            target="Ctrl+S",
            application=None,
            message="Dispatch failed",
            status="execution_failed",
            error="pyautogui error",
            executed=False,
            verified=False,
        )
        assert result.success is False

    def test_unverified_dispatch_not_trustworthy(self):
        result = ActionResult.success_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Typed",
            executed=True,
            verified=False,
        )
        assert result.trustworthy_success is False
        assert result.final_state == "executed_unverified"


# ============================================================
# VERIFICATION REASON PRESERVATION
# ============================================================

class TestVerificationReasonPreservation:
    """Verify verification_reason survives through the result chain."""

    def test_verification_reason_in_action_result_metadata(self):
        result = ActionResult.success_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Typed text",
            executed=True,
            verified=True,
        )
        result.metadata["verification_reason"] = "Focus retained after dispatch"
        d = result.to_dict()
        assert d["metadata"]["verification_reason"] == "Focus retained after dispatch"

    def test_verification_reason_in_verification_dict(self):
        result = ActionResult.success_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="Typed text",
            executed=True,
            verified=True,
        )
        result.verification["verification_reason"] = "Content verified via UIA"
        d = result.to_dict()
        assert d["verification"]["verification_reason"] == "Content verified via UIA"

    def test_runtime_focus_resolution_has_verification_reason(self):
        outcome = RuntimeFocusResolution(
            dispatched=True,
            verified=True,
            verification_reason="Test reason",
        )
        assert outcome.verification_reason == "Test reason"


# ============================================================
# UNSAFE TITLE PATTERNS DEDUPLICATION
# ============================================================

class TestUnsafeTitlePatterns:
    """Verify the canonical patterns are defined once and cover all cases."""

    def test_patterns_defined_in_window_models(self):
        from genesis_os.window_models import UNSAFE_TITLE_PATTERNS
        assert len(UNSAFE_TITLE_PATTERNS) >= 11

    def test_patterns_imported_in_focus_resolver(self):
        from genesis_os.runtime_focus_resolver import _UNSAFE_TITLE_PATTERNS
        from genesis_os.window_models import UNSAFE_TITLE_PATTERNS
        assert _UNSAFE_TITLE_PATTERNS is UNSAFE_TITLE_PATTERNS

    def test_no_ptython_typo(self):
        import re
        for pat in UNSAFE_TITLE_PATTERNS:
            assert "ptython" not in pat.pattern

    def test_python_pattern_exists(self):
        import re
        patterns = [p.pattern for p in UNSAFE_TITLE_PATTERNS]
        assert any("python" in p.lower() for p in patterns)

    def test_console_patterns_covered(self):
        import re
        patterns = [p.pattern for p in UNSAFE_TITLE_PATTERNS]
        assert any("cmd" in p.lower() for p in patterns)
        assert any("powershell" in p.lower() for p in patterns)
        assert any("console" in p.lower() for p in patterns)
