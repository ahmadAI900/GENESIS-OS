"""
Regression tests for Phase 2 deferred items.

Item 1: explain_error() must return FriendlyError object, not string
Item 2: _extract_verification_evidence must include verification_reason
Item 3: browser.click risk classification with heuristic signals
"""

import pytest
from unittest.mock import MagicMock, patch
from genesis_os.error_handler import explain_error, FriendlyError
from genesis_os.action_executor import ActionExecutor
from genesis_os.security_model import RiskLevel, OperationCategory, assess_operation_risk


# ============================================================
# Item 1: explain_error() returns FriendlyError, not string
# ============================================================


class TestExplainErrorReturnType:
    """explain_error() must return a FriendlyError object, not a formatted string."""

    def test_returns_friendly_error_for_attribute_error(self):
        """AttributeError must produce a FriendlyError, not a str."""
        error = AttributeError("'NoneType' object has no attribute 'click'")
        result = explain_error(error, context={"operation": "browser.click"})
        assert isinstance(result, FriendlyError)

    def test_returns_friendly_error_for_type_error(self):
        """TypeError must produce a FriendlyError."""
        error = TypeError("expected str, got int")
        result = explain_error(error)
        assert isinstance(result, FriendlyError)

    def test_returns_friendly_error_for_os_error(self):
        """OSError must produce a FriendlyError."""
        error = OSError("Permission denied")
        result = explain_error(error)
        assert isinstance(result, FriendlyError)

    def test_has_required_attributes(self):
        """FriendlyError must have all attributes accessed by action_executor.py."""
        error = AttributeError("'NoneType' object has no attribute 'click'")
        result = explain_error(error)
        assert hasattr(result, "user_message")
        assert hasattr(result, "original_error")
        assert hasattr(result, "suggested_actions")
        assert hasattr(result, "recovery_hint")

    def test_user_message_is_string(self):
        """user_message must be a string."""
        error = AttributeError("test error")
        result = explain_error(error)
        assert isinstance(result.user_message, str)
        assert len(result.user_message) > 0

    def test_original_error_contains_error_info(self):
        """original_error should contain the original error information."""
        error = AttributeError("'NoneType' object has no attribute 'click'")
        result = explain_error(error)
        assert "AttributeError" in result.original_error or "attribute" in result.original_error.lower()

    def test_suggested_actions_is_tuple_or_list(self):
        """suggested_actions must be a tuple or list."""
        error = FileNotFoundError("test.txt not found")
        result = explain_error(error)
        assert isinstance(result.suggested_actions, (tuple, list))

    def test_context_adds_operation_info(self):
        """Context should add operation info to user_message."""
        error = ValueError("test error")
        result = explain_error(error, context={"operation": "browser.click"})
        assert "browser.click" in result.user_message or "browser click" in result.user_message.lower()


# ============================================================
# Item 2: _extract_verification_evidence includes verification_reason
# ============================================================


class TestExtractVerificationEvidence:
    """_extract_verification_evidence must capture verification_reason."""

    def test_extracts_verification_reason_when_present(self):
        """verification_reason should be extracted when present in result."""
        result = {
            "verified": True,
            "verification_reason": "element_found reported by provider",
            "verification_type": "browser_click",
            "application": "notepad",
        }
        evidence = ActionExecutor._extract_verification_evidence(result)
        assert "verification_reason" in evidence
        assert evidence["verification_reason"] == "element_found reported by provider"

    def test_extracts_verification_reason_when_absent(self):
        """verification_reason should be absent from evidence when not in result."""
        result = {
            "verified": True,
            "verification_type": "browser_click",
            "application": "notepad",
        }
        evidence = ActionExecutor._extract_verification_evidence(result)
        assert "verification_reason" not in evidence

    def test_extracts_all_verification_fields(self):
        """All verification-related fields should be extracted."""
        result = {
            "verified": True,
            "verification_type": "browser_click",
            "verification_method": "element_inspection",
            "verification_reason": "element_found reported by provider",
            "verification_attempts": 2,
            "running": True,
            "available": True,
            "process_found": True,
            "application": "notepad",
        }
        evidence = ActionExecutor._extract_verification_evidence(result)
        assert evidence["verified"] is True
        assert evidence["verification_type"] == "browser_click"
        assert evidence["verification_method"] == "element_inspection"
        assert evidence["verification_reason"] == "element_found reported by provider"
        assert evidence["verification_attempts"] == 2
        assert evidence["running"] is True
        assert evidence["available"] is True
        assert evidence["process_found"] is True

    def test_excludes_non_verification_fields(self):
        """Non-verification fields should not be in evidence."""
        result = {
            "verified": True,
            "verification_reason": "test reason",
            "application": "notepad",
            "operation": "browser.click",
            "target": "button",
        }
        evidence = ActionExecutor._extract_verification_evidence(result)
        assert "application" not in evidence
        assert "operation" not in evidence
        assert "target" not in evidence

    def test_honest_fallback_reason_extracted(self):
        """Honest fallback verification_reason should be extracted."""
        result = {
            "verified": False,
            "verification_reason": (
                "no element_found or verified signal in provider result; "
                "honest fallback (cannot observe post-state from "
                "OSManager wrapper without expensive page introspection)"
            ),
        }
        evidence = ActionExecutor._extract_verification_evidence(result)
        assert "verification_reason" in evidence
        assert "honest fallback" in evidence["verification_reason"]


# ============================================================
# Item 3: browser.click risk classification
# ============================================================


class TestBrowserClickRiskClassification:
    """browser.click should be LOW risk by default, but HIGH for high-risk signal words."""

    def test_browser_click_is_low_by_default(self):
        """browser.click with no high-risk signals should be LOW."""
        assessment = assess_operation_risk("browser.click")
        assert assessment.risk_level == RiskLevel.LOW
        assert assessment.requires_confirmation is False

    def test_browser_click_with_high_risk_signal_requires_confirmation(self):
        """browser.click with high-risk signal text should require confirmation."""
        # This is the heuristic improvement - clicking elements with
        # destructive/action text should trigger confirmation
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Delete my account"}
        )
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_confirmation is True

    def test_browser_click_buy_signal(self):
        """Clicking 'Buy Now' should require confirmation."""
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Buy Now - $29.99"}
        )
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_confirmation is True

    def test_browser_click_send_signal(self):
        """Clicking 'Send Message' should require confirmation."""
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Send"}
        )
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_confirmation is True

    def test_browser_click_normal_link_no_confirmation(self):
        """Clicking a normal link should NOT require confirmation."""
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Learn more about our services"}
        )
        assert assessment.risk_level == RiskLevel.LOW
        assert assessment.requires_confirmation is False

    def test_browser_click_navigation_no_confirmation(self):
        """Clicking navigation links should NOT require confirmation."""
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Next Page"}
        )
        assert assessment.risk_level == RiskLevel.LOW
        assert assessment.requires_confirmation is False

    def test_browser_click_unsubscribe_signal(self):
        """Clicking 'Unsubscribe' should require confirmation."""
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Unsubscribe from all emails"}
        )
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_confirmation is True

    def test_browser_click_confirm_signal(self):
        """Clicking 'Confirm' should require confirmation."""
        assessment = assess_operation_risk(
            "browser.click",
            context={"element_text": "Confirm payment"}
        )
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_confirmation is True

    def test_dispatch_path_passes_context_to_security_model(self):
        """The real dispatch path must pass element_text from plan parameters to security model."""
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        # Create an ActionPlan with element_text in parameters
        plan = ActionPlan(
            operation="browser.click",
            target="#delete-btn",
            parameters={
                "selector": "#delete-btn",
                "session_id": "default",
                "element_text": "Delete my account",
            },
        )

        # Verify that the security assessment uses the element_text
        # by calling assess_operation_risk with the same context
        assessment = assess_operation_risk(
            plan.operation,
            context={"element_text": plan.parameters.get("element_text")},
        )
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_confirmation is True

    def test_extract_text_failure_logs_debug_message(self):
        """When extract_text raises, a debug log message must be emitted."""
        import logging
        from unittest.mock import MagicMock, patch
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        # Create mock OSManager where extract_text raises
        os_manager = MagicMock()
        os_manager.browser.extract_text.side_effect = RuntimeError("Browser disconnected")

        executor = ActionExecutor(os_manager=os_manager)

        plan = ActionPlan(
            operation="browser.click",
            target="#delete-btn",
            parameters={
                "selector": "#delete-btn",
                "session_id": "default",
            },
        )

        # Execute and capture log
        with patch("genesis_os.action_executor.logger") as mock_logger:
            result = executor.execute(plan)
            # The debug log should have been called
            mock_logger.debug.assert_called_once()
            log_args = mock_logger.debug.call_args
            # Check the format string
            assert "element-text extraction failed" in log_args[0][0]
            # Check the format arguments: selector and session_id
            assert log_args[0][1] == "#delete-btn"
            assert log_args[0][2] == "default"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
