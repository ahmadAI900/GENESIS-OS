"""
Genesis OS — Level 3 Human-Friendly Error Handling.

Transforms raw exceptions into meaningful, user-friendly explanations:

    FileNotFoundError
    PermissionError
    TimeoutError
    Application launch failure
    Window not found
    Unknown application
    Browser failure
    Document parsing failure

Into natural language explanations that users can understand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FriendlyError:
    """A user-friendly error explanation."""
    original_error: str
    error_type: str
    user_message: str
    technical_details: Optional[str] = None
    suggested_actions: tuple = ()
    recovery_hint: Optional[str] = None


class ErrorHandler:
    """
    Transforms raw errors into human-friendly explanations.
    
    The handler preserves technical details for logging while
    presenting clear, actionable messages to users.
    """

    VERSION = "3.0.0"

    # Error type mappings
    ERROR_MAPPINGS = {
        # File system errors
        "FileNotFoundError": {
            "user_message": "I couldn't find the file you're looking for.",
            "suggested_actions": (
                "Check the file name and try again",
                "Use 'find my [file]' to locate it",
                "Make sure the file hasn't been moved or deleted",
            ),
        },
        "PermissionError": {
            "user_message": "I don't have permission to access that file or folder.",
            "suggested_actions": (
                "Check if the file is open in another program",
                "Run Genesis as administrator if needed",
                "Check folder permissions",
            ),
        },
        "IsADirectoryError": {
            "user_message": "That path is a folder, not a file.",
            "suggested_actions": (
                "Use folder operations instead",
                "Specify a file within the folder",
            ),
        },
        "FileExistsError": {
            "user_message": "A file with that name already exists.",
            "suggested_actions": (
                "Use a different name",
                "Delete or rename the existing file first",
            ),
        },
        "NotADirectoryError": {
            "user_message": "That path is not a valid folder.",
            "suggested_actions": (
                "Check the folder path",
                "Create the folder first if needed",
            ),
        },
        "OSError": {
            "user_message": "A system error occurred while accessing the file system.",
            "suggested_actions": (
                "Check if the path is valid",
                "Ensure the drive has enough space",
                "Try again in a moment",
            ),
        },

        # Application errors
        "ApplicationNotFoundError": {
            "user_message": "I couldn't find that application on your system.",
            "suggested_actions": (
                "Check the application name",
                "Make sure it's installed",
                "Try 'list applications' to see available apps",
            ),
        },
        "ApplicationLaunchError": {
            "user_message": "I found the application but couldn't start it.",
            "suggested_actions": (
                "The app might already be running",
                "Try closing it first and trying again",
                "Check if the app needs updates",
            ),
        },
        "ApplicationNotRunningError": {
            "user_message": "That application doesn't appear to be running.",
            "suggested_actions": (
                "Open the application first",
                "Check the application name",
            ),
        },

        # Browser errors
        "BrowserError": {
            "user_message": "I encountered an issue with the browser.",
            "suggested_actions": (
                "Make sure a browser is installed",
                "Try a different browser",
                "Check your internet connection",
            ),
        },
        "NavigationError": {
            "user_message": "I couldn't navigate to that website.",
            "suggested_actions": (
                "Check the URL is correct",
                "Verify your internet connection",
                "The site might be temporarily unavailable",
            ),
        },

        # Network errors
        "ConnectionError": {
            "user_message": "I couldn't connect to the network.",
            "suggested_actions": (
                "Check your internet connection",
                "Verify Wi-Fi is connected",
                "Try again in a moment",
            ),
        },
        "TimeoutError": {
            "user_message": "The operation took too long and timed out.",
            "suggested_actions": (
                "Try again - it might work on a second attempt",
                "Check your connection speed",
                "The server might be busy",
            ),
        },

        # Process errors
        "ProcessNotFoundError": {
            "user_message": "I couldn't find that process.",
            "suggested_actions": (
                "Check the process name",
                "Use 'list processes' to see running processes",
            ),
        },

        # Generic
        "UnknownError": {
            "user_message": "An unexpected error occurred.",
            "suggested_actions": (
                "Try rephrasing your request",
                "Try a simpler operation first",
                "Let me know what you were trying to do",
            ),
        },
    }

    def __init__(self):
        pass

    def handle(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> FriendlyError:
        """
        Convert an exception into a friendly error.
        
        Args:
            error: The exception that occurred
            context: Optional context about what was being attempted
            
        Returns:
            FriendlyError with user-friendly message and suggestions
        """
        error_type = type(error).__name__
        error_str = str(error)

        # Try to find a specific mapping
        mapping = self.ERROR_MAPPINGS.get(error_type)
        
        if not mapping:
            # Try to match by error message content
            mapping = self._match_by_message(error_str)

        if not mapping:
            mapping = self.ERROR_MAPPINGS["UnknownError"]

        # Build user message with context
        user_message = mapping["user_message"]
        if context:
            user_message = self._add_context(user_message, context, error_str)

        return FriendlyError(
            original_error=error_str,
            error_type=error_type,
            user_message=user_message,
            technical_details=error_str if context and context.get("include_technical") else None,
            suggested_actions=mapping.get("suggested_actions", ()),
            recovery_hint=mapping.get("recovery_hint"),
        )

    def _match_by_message(self, error_str: str) -> Optional[Dict[str, Any]]:
        """Match error by message content."""
        error_lower = error_str.lower()

        # File not found patterns
        if any(p in error_lower for p in ["not found", "no such file", "cannot find"]):
            return self.ERROR_MAPPINGS["FileNotFoundError"]

        # Permission patterns
        if any(p in error_lower for p in ["permission denied", "access denied", "unauthorized"]):
            return self.ERROR_MAPPINGS["PermissionError"]

        # Application not found
        if any(p in error_lower for p in ["application not found", "app not found", "executable not found"]):
            return self.ERROR_MAPPINGS["ApplicationNotFoundError"]

        # Application launch
        if any(p in error_lower for p in ["failed to launch", "could not start", "launch failed"]):
            return self.ERROR_MAPPINGS["ApplicationLaunchError"]

        # Timeout
        if any(p in error_lower for p in ["timeout", "timed out", "took too long"]):
            return self.ERROR_MAPPINGS["TimeoutError"]

        # Connection
        if any(p in error_lower for p in ["connection refused", "connection failed", "network unreachable"]):
            return self.ERROR_MAPPINGS["ConnectionError"]

        return None

    def _add_context(self, base_message: str, context: Dict[str, Any], error_str: str) -> str:
        """Add contextual information to the error message."""
        parts = [base_message]

        operation = context.get("operation")
        if operation:
            parts.append(f"This happened while trying to {operation}.")

        target = context.get("target")
        if target:
            parts.append(f"Target: {target}")

        application = context.get("application")
        if application:
            parts.append(f"Application: {application}")

        return " ".join(parts)

    def format_for_user(self, friendly_error: FriendlyError) -> str:
        """Format a friendly error for user display."""
        lines = [friendly_error.user_message]

        if friendly_error.suggested_actions:
            lines.append("\nYou could try:")
            for action in friendly_error.suggested_actions:
                lines.append(f"  • {action}")

        if friendly_error.recovery_hint:
            lines.append(f"\nHint: {friendly_error.recovery_hint}")

        return "\n".join(lines)


# Convenience function
def explain_error(error: Exception, context: Optional[Dict[str, Any]] = None) -> FriendlyError:
    """Quick function to get a user-friendly error explanation.

    Returns a FriendlyError object with .user_message, .original_error,
    .suggested_actions, and .recovery_hint attributes.

    Callers that need the formatted string can use:
        handler = ErrorHandler()
        handler.format_for_user(friendly)
    """
    handler = ErrorHandler()
    return handler.handle(error, context)