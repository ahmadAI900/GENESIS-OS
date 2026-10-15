"""
Genesis OS — Level 3.7 Failure Classifier.

Classifies execution failures into actionable categories so that
recovery strategies are selected deterministically rather than
blindly retried.

Categories (from spec):
    application_unavailable
    file_moved
    file_renamed
    permission_denied
    browser_failure
    network_failure
    wrong_target
    unexpected_application_state
    timeout
    partial_completion
    unknown
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FailureCategory(str, Enum):
    APPLICATION_UNAVAILABLE = "application_unavailable"
    FILE_MOVED = "file_moved"
    FILE_RENAMED = "file_renamed"
    PERMISSION_DENIED = "permission_denied"
    BROWSER_FAILURE = "browser_failure"
    NETWORK_FAILURE = "network_failure"
    WRONG_TARGET = "wrong_target"
    UNEXPECTED_APPLICATION_STATE = "unexpected_application_state"
    TIMEOUT = "timeout"
    PARTIAL_COMPLETION = "partial_completion"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureClassification:
    """Result of classifying an execution failure."""
    category: FailureCategory
    confidence: float
    original_error: str
    diagnostic: str
    recovery_hint: str
    retryable: bool

    def to_dict(self):
        return {
            "category": self.category.value,
            "confidence": self.confidence,
            "original_error": self.original_error,
            "diagnostic": self.diagnostic,
            "recovery_hint": self.recovery_hint,
            "retryable": self.retryable,
        }


class FailureClassifier:
    """
    Classifies execution failures into actionable categories.

    Uses error messages, exception types, operation context,
    and execution results to determine the most likely failure
    mode and appropriate recovery strategy.
    """

    VERSION = "3.7.0"

    def classify(
        self,
        error: str,
        operation: str = "",
        exception_type: str = "",
        execution_result=None,
    ) -> FailureClassification:
        """
        Classify a failure into a category.

        Args:
            error: The error message string
            operation: The operation that was attempted
            exception_type: The Python exception class name
            execution_result: Optional ActionResult for context

        Returns:
            FailureClassification with category, diagnostic, and recovery hint
        """
        error_lower = (error or "").lower()
        exc_lower = (exception_type or "").lower()
        op_lower = (operation or "").lower()

        # --- permission denied ---
        if self._match_patterns(error_lower, exc_lower, [
            "permission denied", "access denied", "unauthorized",
            "permissionerror", "winerror 5", "winerror 1314",
        ]):
            return FailureClassification(
                category=FailureCategory.PERMISSION_DENIED,
                confidence=0.95,
                original_error=error,
                diagnostic="The operation was blocked by OS permissions.",
                recovery_hint="Try running with appropriate permissions or choose a different target.",
                retryable=False,
            )

        # --- timeout ---
        if self._match_patterns(error_lower, exc_lower, [
            "timeout", "timed out", "took too long",
            "timeouterror", "等待操作超时",
        ]):
            return FailureClassification(
                category=FailureCategory.TIMEOUT,
                confidence=0.90,
                original_error=error,
                diagnostic="The operation exceeded its time limit.",
                recovery_hint="The target may be slow to respond. Retry or increase timeout.",
                retryable=True,
            )

        # --- network failure ---
        if self._match_patterns(error_lower, exc_lower, [
            "connection refused", "connection failed", "network unreachable",
            "connectionerror", "connectionreseterror", "connection aborted",
            "name or service not known", "failed to resolve",
            "ssl", "certificate", "remote disconnected",
        ]):
            return FailureClassification(
                category=FailureCategory.NETWORK_FAILURE,
                confidence=0.90,
                original_error=error,
                diagnostic="A network connectivity issue prevented the operation.",
                recovery_hint="Check internet connection and retry.",
                retryable=True,
            )

        # --- browser failure ---
        if self._match_patterns(error_lower, exc_lower, [
            "browser", "playwright", "selenium", "chromedriver",
            "page.", "navigate", "element not found", "no such element",
            "session not created", "web driver",
        ]) or op_lower.startswith("browser."):
            return FailureClassification(
                category=FailureCategory.BROWSER_FAILURE,
                confidence=0.85,
                original_error=error,
                diagnostic="The browser operation failed.",
                recovery_hint="Browser may need to be restarted or the page reloaded.",
                retryable=True,
            )

        # --- file moved ---
        if self._match_patterns(error_lower, exc_lower, [
            "no such file", "file not found", "path not found",
            "filenotfounderror",
        ]) and op_lower.startswith("file."):
            # Distinguish moved vs wrong target
            if execution_result and hasattr(execution_result, "verification"):
                ver = execution_result.verification or {}
                if ver.get("verification_type") == "file_exists":
                    return FailureClassification(
                        category=FailureCategory.FILE_MOVED,
                        confidence=0.80,
                        original_error=error,
                        diagnostic="The file was expected at this path but is no longer there.",
                        recovery_hint="The file may have been moved. Search for it by name.",
                        retryable=True,
                    )

            return FailureClassification(
                category=FailureCategory.WRONG_TARGET,
                confidence=0.70,
                original_error=error,
                diagnostic="The specified file path does not exist.",
                recovery_hint="Verify the file path or search for the file by name.",
                retryable=True,
            )

        # --- file renamed ---
        if self._match_patterns(error_lower, exc_lower, [
            "no such file", "file not found",
        ]) and op_lower.startswith("file."):
            return FailureClassification(
                category=FailureCategory.FILE_RENAMED,
                confidence=0.65,
                original_error=error,
                diagnostic="The file was not found at the expected path.",
                recovery_hint="The file may have been renamed. Search for it by name or content.",
                retryable=True,
            )

        # --- application unavailable ---
        if self._match_patterns(error_lower, exc_lower, [
            "application not found", "app not found", "executable not found",
            "could not find", "not installed", "no such application",
            "file not found",
        ]) and op_lower.startswith("application."):
            return FailureClassification(
                category=FailureCategory.APPLICATION_UNAVAILABLE,
                confidence=0.85,
                original_error=error,
                diagnostic="The target application could not be found on this system.",
                recovery_hint="Try an alternative application or verify the name.",
                retryable=True,
            )

        # --- unexpected application state ---
        if self._match_patterns(error_lower, exc_lower, [
            "already running", "already closed", "state mismatch",
            "unexpected state", "verification_failed",
            "application was expected",
        ]):
            return FailureClassification(
                category=FailureCategory.UNEXPECTED_APPLICATION_STATE,
                confidence=0.80,
                original_error=error,
                diagnostic="The application is not in the expected state.",
                recovery_hint="Re-observe the application state and adjust the plan.",
                retryable=True,
            )

        # --- wrong target (general) ---
        if self._match_patterns(error_lower, exc_lower, [
            "not found", "does not exist", "missing",
            "invalid path", "bad path",
        ]):
            return FailureClassification(
                category=FailureCategory.WRONG_TARGET,
                confidence=0.70,
                original_error=error,
                diagnostic="The specified target could not be found.",
                recovery_hint="Verify the target name or path.",
                retryable=True,
            )

        # --- partial completion ---
        if execution_result is not None:
            if hasattr(execution_result, "executed") and execution_result.executed:
                if hasattr(execution_result, "verified") and not execution_result.verified:
                    return FailureClassification(
                        category=FailureCategory.PARTIAL_COMPLETION,
                        confidence=0.75,
                        original_error=error,
                        diagnostic="The operation executed but verification failed.",
                        recovery_hint="The system state may have changed. Re-observe and verify.",
                        retryable=True,
                    )

        return FailureClassification(
            category=FailureCategory.UNKNOWN,
            confidence=0.50,
            original_error=error,
            diagnostic="The failure could not be automatically classified.",
            recovery_hint="Review the error and try a different approach.",
            retryable=False,
        )

    @staticmethod
    def _match_patterns(
        error_lower: str,
        exc_lower: str,
        patterns: list[str],
    ) -> bool:
        """Check if any pattern matches the error or exception type."""
        for pattern in patterns:
            if pattern in error_lower or pattern in exc_lower:
                return True
        return False
