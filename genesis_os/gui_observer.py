"""
Genesis OS — Phase 6 GUI Observer & Verifier.

Observation: reading actual OS state after an action.
Verification: comparing observed state against expected state.

Every GUI action must produce observation evidence.
Verification must be capability-specific, not generic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from genesis_os.window_models import WindowIdentity, WindowResolver, WindowState
from genesis_os.contracts import (
    Observation as ObservationContract,
    Verification as VerificationContract,
)


def _checked_verification(method):
    """Phase 1 decorator: every GUIVerifier verdict must satisfy
    the Verification contract (verified bool + non-empty reason)."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        VerificationContract.from_gui_result(result)
        return result

    return wrapper


@dataclass
class Observation:
    """A single observation of OS state."""
    timestamp: float = field(default_factory=time.monotonic)
    foreground_window: Optional[WindowIdentity] = None
    all_windows: List[WindowIdentity] = field(default_factory=list)
    text_content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "timestamp": self.timestamp,
        }
        if self.foreground_window:
            result["foreground_window"] = self.foreground_window.to_dict()
        if self.text_content is not None:
            result["text_content"] = self.text_content
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        result["window_count"] = len(self.all_windows)
        return result


@dataclass
class VerificationResult:
    """Result of a verification check."""
    verified: bool
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    observation: Optional[Observation] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "verified": self.verified,
            "reason": self.reason,
        }
        if self.evidence:
            result["evidence"] = dict(self.evidence)
        if self.observation:
            result["observation"] = self.observation.to_dict()
        return result


class GUIObserver:
    """
    Observes actual OS state after GUI actions.

    Provides capability-specific observation methods:
    - observe_foreground: which window has focus
    - observe_windows: all visible windows
    - observe_focus_retained: focus stayed on expected window
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._resolver = WindowResolver()

    @property
    def available(self) -> bool:
        return self._resolver.available

    def observe_foreground(self) -> Optional[WindowIdentity]:
        """Observe the current foreground window."""
        return self._resolver.get_foreground()

    def observe_windows(self) -> List[WindowIdentity]:
        """Observe all visible windows."""
        return self._resolver.enumerate_windows()

    def observe_focus_retained(
        self,
        expected_hwnd: int,
        *,
        settle_seconds: float = 0.05,
    ) -> bool:
        """Check that focus stayed on the expected window."""
        return self._resolver.verify_focus_retained(
            expected_hwnd, settle_seconds=settle_seconds
        )

    def take_snapshot(self) -> Observation:
        """Take a complete observation snapshot."""
        fg = self.observe_foreground()
        windows = self.observe_windows()
        snapshot = Observation(
            foreground_window=fg,
            all_windows=windows,
        )
        # Phase 1 contract: malformed snapshots rejected at source.
        ObservationContract.from_snapshot(snapshot)
        return snapshot

    def wait_for_condition(
        self,
        condition: Callable[[], bool],
        timeout: float = 10.0,
        poll_interval: float = 0.2,
    ) -> bool:
        """Wait for a condition to become true."""
        timeout = min(max(0.0, timeout), 120.0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if condition():
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False


class GUIVerifier:
    """
    Capability-specific verification.

    Each verification method compares expected state against
    observed state and returns honest evidence.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._observer = GUIObserver()

    @property
    def available(self) -> bool:
        return self._observer.available

    @_checked_verification
    def verify_window_focused(
        self,
        expected_hwnd: int,
    ) -> VerificationResult:
        """Verify a specific window is in the foreground."""
        fg = self._observer.observe_foreground()
        if fg is None:
            return VerificationResult(
                verified=False,
                reason="Could not observe foreground window",
            )
        if fg.hwnd == expected_hwnd:
            return VerificationResult(
                verified=True,
                reason=f"Window hwnd={expected_hwnd} is foreground",
                evidence={"foreground_hwnd": fg.hwnd, "title": fg.title},
            )
        return VerificationResult(
            verified=False,
            reason=f"Expected hwnd={expected_hwnd} but foreground is hwnd={fg.hwnd} title='{fg.title}'",
            evidence={
                "expected_hwnd": expected_hwnd,
                "actual_hwnd": fg.hwnd,
                "actual_title": fg.title,
            },
        )

    @_checked_verification
    def verify_focus_retained(
        self,
        expected_hwnd: int,
    ) -> VerificationResult:
        """Verify focus was retained after dispatch."""
        retained = self._observer.observe_focus_retained(expected_hwnd)
        if retained:
            fg = self._observer.observe_foreground()
            return VerificationResult(
                verified=True,
                reason="Focus retained on expected window",
                evidence={"hwnd": expected_hwnd, "title": fg.title if fg else ""},
            )
        fg = self._observer.observe_foreground()
        return VerificationResult(
            verified=False,
            reason="Focus changed during dispatch",
            evidence={
                "expected_hwnd": expected_hwnd,
                "actual_hwnd": fg.hwnd if fg else None,
                "actual_title": fg.title if fg else "",
            },
        )

    @_checked_verification
    def verify_window_exists(
        self,
        title_pattern: str,
    ) -> VerificationResult:
        """Verify a window matching a pattern exists."""
        win = self._observer._resolver.find_window(title_pattern)
        if win:
            return VerificationResult(
                verified=True,
                reason=f"Window matching '{title_pattern}' found",
                evidence=win.to_dict(),
            )
        return VerificationResult(
            verified=False,
            reason=f"No window matching '{title_pattern}' found",
        )

    @_checked_verification
    def verify_window_not_exists(
        self,
        title_pattern: str,
    ) -> VerificationResult:
        """Verify no window matching a pattern exists."""
        windows = self._observer.observe_windows()
        import re
        matches = []
        for w in windows:
            try:
                if re.search(title_pattern, w.title, re.IGNORECASE):
                    matches.append(w)
            except re.error:
                if title_pattern.lower() in w.title.lower():
                    matches.append(w)
        if not matches:
            return VerificationResult(
                verified=True,
                reason=f"No window matching '{title_pattern}' found (expected)",
            )
        return VerificationResult(
            verified=False,
            reason=f"Found {len(matches)} window(s) matching '{title_pattern}'",
            evidence={"matching_windows": [w.to_dict() for w in matches]},
        )

    @_checked_verification
    def verify_condition(
        self,
        condition: Callable[[], bool],
        timeout: float = 5.0,
        description: str = "condition",
    ) -> VerificationResult:
        """Verify an arbitrary condition becomes true within timeout."""
        met = self._observer.wait_for_condition(condition, timeout)
        if met:
            return VerificationResult(
                verified=True,
                reason=f"{description} met within {timeout}s",
            )
        return VerificationResult(
            verified=False,
            reason=f"{description} not met within {timeout}s",
        )
