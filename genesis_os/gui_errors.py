"""
Genesis OS — Phase 6 GUI Error Taxonomy.

Structured error classification for GUI/application operations.
Every GUI failure should map to one of these codes so that
recovery logic, user messages, and debugging are consistent.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class GUIErrorCode(str, Enum):
    """Canonical GUI error codes."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_FAILURE = "provider_failure"
    PROVIDER_TIMEOUT = "provider_timeout"

    APPLICATION_NOT_FOUND = "application_not_found"
    APPLICATION_NOT_RUNNING = "application_not_running"
    APPLICATION_UNAVAILABLE = "application_unavailable"

    WINDOW_NOT_FOUND = "window_not_found"
    WINDOW_AMBIGUOUS = "window_ambiguous"
    WINDOW_NOT_FOCUSED = "window_not_focused"
    WINDOW_DESTROYED = "window_destroyed"

    TARGET_NOT_FOUND = "target_not_found"
    TARGET_AMBIGUOUS = "target_ambiguous"
    TARGET_UNSUPPORTED = "target_unsupported"
    TARGET_STALE = "target_stale"

    DISPATCH_FAILURE = "dispatch_failure"
    DISPATCH_TIMEOUT = "dispatch_timeout"

    OBSERVATION_FAILURE = "observation_failure"
    VERIFICATION_FAILURE = "verification_failure"

    FOCUS_LOST = "focus_lost"
    UNSAFE_TARGET = "unsafe_target"

    ACCESS_DENIED = "access_denied"
    PLATFORM_UNSUPPORTED = "platform_unsupported"

    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GUIError:
    """Structured GUI error with code, message, and optional context."""

    code: GUIErrorCode
    message: str
    detail: Optional[str] = None
    provider: Optional[str] = None
    retryable: bool = False

    def to_dict(self) -> dict:
        result = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.detail:
            result["detail"] = self.detail
        if self.provider:
            result["provider"] = self.provider
        if self.retryable:
            result["retryable"] = True
        return result


def gui_error(
    code: GUIErrorCode,
    message: str,
    *,
    detail: Optional[str] = None,
    provider: Optional[str] = None,
    retryable: bool = False,
) -> GUIError:
    """Convenience factory for GUIError."""
    return GUIError(
        code=code,
        message=message,
        detail=detail,
        provider=provider,
        retryable=retryable,
    )
