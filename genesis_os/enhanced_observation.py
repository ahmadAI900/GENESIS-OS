"""
Genesis OS — Level 3 Enhanced Observation Loop.

Extends the base ObservationLoop with comprehensive verification
for ALL operation types: media, volume, display, hardware, clipboard,
window, notes, packages, web research, spreadsheet, document, and
advanced filesystem/browser operations.

Usage:
    EnhancedObservationLoop wraps ObservationLoop and delegates
    existing operations to it while adding new observation methods
    for previously uncovered operation types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .action_plan import ActionPlan
from .action_result import ActionResult
from .observation_loop import ObservationLoop, ObservationResult
from .os_manager import OSManager


@dataclass(frozen=True)
class EnhancedObservationResult:
    """Extended observation result with confidence scoring."""

    step_id: str
    operation: str
    target: str
    expected_state: Dict[str, Any]
    actual_state: Dict[str, Any]
    matches_expected: bool
    discrepancy: Optional[str] = None
    enhanced_checks: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "target": self.target,
            "expected_state": dict(self.expected_state),
            "actual_state": dict(self.actual_state),
            "matches_expected": self.matches_expected,
            "discrepancy": self.discrepancy,
            "enhanced_checks": dict(self.enhanced_checks),
            "confidence": self.confidence,
        }

    def to_observation_result(self) -> ObservationResult:
        """Downgrade to base ObservationResult for backward compatibility."""
        return ObservationResult(
            step_id=self.step_id,
            operation=self.operation,
            target=self.target,
            expected_state=dict(self.expected_state),
            actual_state=dict(self.actual_state),
            matches_expected=self.matches_expected,
            discrepancy=self.discrepancy,
            metadata={
                "enhanced": True,
                "confidence": self.confidence,
                "enhanced_checks": dict(self.enhanced_checks),
            },
        )


class EnhancedObservationLoop:
    """
    Extended observation loop covering ALL Genesis OS operation types.

    Delegates to the base ObservationLoop for existing operations
    and adds verification for media, volume, display, hardware,
    clipboard, window, notes, packages, web research, spreadsheet,
    and document operations.
    """

    VERSION = "3.10.0"

    def __init__(self, os_manager: OSManager):
        if os_manager is None:
            raise ValueError("EnhancedObservationLoop requires an OSManager.")
        self.os_manager = os_manager
        self._base_loop = ObservationLoop(os_manager)

    def observe(
        self,
        step_id: str,
        plan: ActionPlan,
        execution_result: ActionResult,
    ) -> EnhancedObservationResult:
        """
        Observe actual system state after step execution.

        Uses enhanced observation for new operation types,
        delegates to the base loop for existing ones.
        """
        op = plan.operation

        if self._is_enhanced_operation(op):
            expected = self._derive_expected_state(plan, execution_result)
            actual = self._observe_actual_state(plan)
            matches, discrepancy = self._compare_states(expected, actual)
            enhanced_checks = self._run_enhanced_checks(plan)
            confidence = self._compute_confidence(expected, actual, enhanced_checks)

            return EnhancedObservationResult(
                step_id=step_id,
                operation=plan.operation,
                target=plan.target or "",
                expected_state=expected,
                actual_state=actual,
                matches_expected=matches,
                discrepancy=discrepancy,
                enhanced_checks=enhanced_checks,
                confidence=confidence,
            )

        base_result = self._base_loop.observe(step_id, plan, execution_result)
        return EnhancedObservationResult(
            step_id=base_result.step_id,
            operation=base_result.operation,
            target=base_result.target,
            expected_state=base_result.expected_state,
            actual_state=base_result.actual_state,
            matches_expected=base_result.matches_expected,
            discrepancy=base_result.discrepancy,
            enhanced_checks=base_result.metadata,
            confidence=1.0 if base_result.matches_expected else 0.5,
        )

    # =========================================================
    # OPERATION CLASSIFICATION
    # =========================================================

    @staticmethod
    def _is_enhanced_operation(op: str) -> bool:
        """Check if this operation uses enhanced observation."""
        return op.startswith((
            "media.", "volume.", "display.", "hardware.",
            "clipboard.", "window.", "notes.", "packages.",
            "web.", "spreadsheet.", "document.",
        )) or op in (
            "file.create", "file.read", "file.copy",
            "browser.open_url", "browser.search",
        )

    # =========================================================
    # EXPECTED STATE DERIVATION
    # =========================================================

    def _derive_expected_state(
        self,
        plan: ActionPlan,
        execution_result: ActionResult,
    ) -> Dict[str, Any]:
        """Derive expected state for enhanced operation types."""
        expected: Dict[str, Any] = {
            "operation": plan.operation,
            "target": plan.target,
            "application": plan.application,
        }
        op = plan.operation
        params = plan.parameters

        if op == "media.transport":
            expected.update({
                "media_action": params.get("action", plan.target),
                "media_dispatched": True,
            })

        elif op == "volume.step":
            expected.update({
                "direction": params.get("direction", plan.target),
                "steps": params.get("steps", 2),
                "volume_changed": True,
            })

        elif op == "volume.set":
            expected.update({
                "target_volume": params.get("percent"),
                "volume_changed": True,
            })

        elif op == "volume.mute":
            expected.update({
                "muted": params.get("muted"),
                "mute_toggled": True,
            })

        elif op == "display.brightness_set":
            expected.update({
                "target_brightness": params.get("percent"),
                "direction": params.get("direction"),
                "brightness_changed": True,
            })

        elif op == "clipboard.copy":
            expected.update({
                "clipboard_text": params.get("text", plan.target),
                "clipboard_matches": True,
            })

        elif op == "clipboard.paste":
            expected.update({
                "clipboard_has_content": True,
            })

        elif op == "notes.create":
            expected.update({
                "note_created": True,
                "note_text": params.get("text", plan.target),
                "note_path": params.get("path"),
            })

        elif op == "spreadsheet.sort":
            expected.update({
                "sort_column": params.get("column", plan.target),
                "descending": params.get("descending", True),
                "sort_applied": True,
            })

        elif op == "document.create_docx":
            expected.update({
                "document_created": True,
                "document_title": params.get("title", plan.target),
                "document_path": plan.target,
            })

        elif op == "web.research":
            expected.update({
                "query": params.get("query", plan.target),
                "max_results": params.get("max_results", 5),
                "research_completed": True,
            })

        elif op == "hardware.battery":
            expected.update({
                "battery_query": True,
            })

        elif op == "hardware.stats":
            expected.update({
                "stats_query": True,
            })

        elif op == "window.minimize_all":
            expected.update({
                "all_minimized": True,
            })

        elif op == "window.restore":
            expected.update({
                "windows_restored": True,
            })

        elif op == "window.show_desktop":
            expected.update({
                "desktop_toggled": True,
            })

        elif op == "packages.search":
            expected.update({
                "search_query": params.get("query", plan.target),
                "search_completed": True,
            })

        elif op == "packages.install":
            expected.update({
                "package_id": plan.target,
                "package_installed": True,
            })

        elif op == "packages.uninstall":
            expected.update({
                "package_id": plan.target,
                "package_uninstalled": True,
            })

        elif op == "file.create":
            expected.update({
                "file_exists": True,
                "file_path": plan.target,
                "content": params.get("content", ""),
                "content_matches": True,
            })

        elif op == "file.read":
            expected.update({
                "file_exists": True,
                "file_path": plan.target,
                "readable": True,
            })

        elif op == "file.copy":
            expected.update({
                "file_exists": True,
                "file_path": params.get("destination"),
                "source_exists": True,
                "source_path": plan.target,
            })

        elif op == "browser.open_url":
            expected.update({
                "browser_opened": True,
                "url": plan.parameters.get("url", plan.target),
            })

        elif op == "browser.search":
            expected.update({
                "browser_opened": True,
            })

        if execution_result.execution:
            expected["execution_evidence"] = execution_result.execution
        if execution_result.verification:
            expected["verification_evidence"] = execution_result.verification

        return expected

    # =========================================================
    # ACTUAL STATE OBSERVATION
    # =========================================================

    def _observe_actual_state(self, plan: ActionPlan) -> Dict[str, Any]:
        """Query actual system state for enhanced operations."""
        actual: Dict[str, Any] = {}
        op = plan.operation

        try:
            if op == "media.transport":
                actual.update(self._observe_media(plan))
            elif op.startswith("volume."):
                actual.update(self._observe_volume(plan))
            elif op.startswith("display."):
                actual.update(self._observe_brightness(plan))
            elif op.startswith("clipboard."):
                actual.update(self._observe_clipboard(plan))
            elif op.startswith("hardware."):
                actual.update(self._observe_hardware(plan))
            elif op.startswith("window."):
                actual.update(self._observe_window(plan))
            elif op.startswith("browser."):
                actual.update(self._observe_browser_advanced(plan))
            elif op.startswith("file."):
                actual.update(self._observe_filesystem_advanced(plan))
            elif op.startswith("spreadsheet."):
                actual.update(self._observe_spreadsheet(plan))
            elif op.startswith("document."):
                actual.update(self._observe_document(plan))
            elif op.startswith("notes."):
                actual.update(self._observe_notes(plan))
            elif op.startswith("web."):
                actual.update(self._observe_network(plan))
            elif op.startswith("packages."):
                actual.update(self._observe_packages(plan))
        except Exception as exc:
            actual["observation_error"] = str(exc)

        return actual

    # =========================================================
    # INDIVIDUAL OBSERVERS
    # =========================================================

    def _observe_media(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check media transport state after execution."""
        media = self.os_manager.media
        action = plan.parameters.get("action", plan.target or "")

        return {
            "media_action": action,
            "media_available": media.available,
            "media_observed": True,
            "verification_type": "media_dispatch",
        }

    def _observe_volume(self, plan: ActionPlan) -> Dict[str, Any]:
        """Verify volume level changed."""
        op = plan.operation
        volume_result = self.os_manager.media.get_volume()

        actual: Dict[str, Any] = {
            "volume_available": volume_result.get("available", False),
            "volume_percent": volume_result.get("volume_percent"),
            "volume_muted": volume_result.get("muted"),
        }

        if op == "volume.step":
            actual["direction"] = plan.parameters.get("direction", plan.target)
            actual["steps"] = plan.parameters.get("steps", 2)
        elif op == "volume.set":
            actual["target_volume"] = plan.parameters.get("percent")
        elif op == "volume.mute":
            actual["muted"] = volume_result.get("muted")

        actual["verification_type"] = "audio_endpoint_readback"
        return actual

    def _observe_brightness(self, plan: ActionPlan) -> Dict[str, Any]:
        """Verify brightness changed."""
        display = self.os_manager.display
        brightness = display.get_brightness()

        actual: Dict[str, Any] = {
            "display_available": display.available,
            "brightness_percent": brightness.get("brightness_percent"),
            "per_display": brightness.get("per_display", []),
        }

        if plan.operation == "display.brightness_set":
            actual["target_brightness"] = plan.parameters.get("percent")
            actual["direction"] = plan.parameters.get("direction")

        actual["verification_type"] = "display_readback"
        return actual

    def _observe_clipboard(self, plan: ActionPlan) -> Dict[str, Any]:
        """Verify clipboard content."""
        clipboard = self.os_manager.clipboard
        op = plan.operation

        actual: Dict[str, Any] = {
            "clipboard_available": clipboard.available,
        }

        if op == "clipboard.copy":
            expected_text = plan.parameters.get("text", plan.target or "")
            paste_result = clipboard.paste()
            actual_content = paste_result.get("content_preview", "")
            actual["clipboard_content_preview"] = actual_content
            actual["clipboard_matches"] = (
                isinstance(actual_content, str)
                and len(expected_text) > 0
                and expected_text[:500] in actual_content
            )
        elif op == "clipboard.paste":
            paste_result = clipboard.paste()
            actual["clipboard_content_preview"] = paste_result.get("content_preview", "")
            actual["clipboard_has_content"] = not paste_result.get("empty", True)

        actual["verification_type"] = "clipboard_readback"
        return actual

    def _observe_hardware(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check hardware status."""
        hardware = self.os_manager.hardware
        op = plan.operation

        actual: Dict[str, Any] = {
            "hardware_available": hardware.available,
        }

        if op == "hardware.battery":
            battery = hardware.battery()
            actual.update({
                "battery_percent": battery.get("battery_percent"),
                "plugged_in": battery.get("plugged_in"),
                "battery_status": battery.get("status"),
                "battery_present": battery.get("battery_present", True),
            })
            actual["verification_type"] = "hardware_query"
        elif op == "hardware.stats":
            stats = hardware.system_stats()
            actual.update({
                "cpu_percent": stats.get("cpu_percent"),
                "memory_percent": stats.get("memory_percent"),
                "memory_used_gb": stats.get("memory_used_gb"),
                "memory_total_gb": stats.get("memory_total_gb"),
                "uptime_hours": stats.get("uptime_hours"),
                "platform": stats.get("platform"),
            })
            actual["verification_type"] = "hardware_query"

        return actual

    def _observe_window(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check window state after operation."""
        windows = self.os_manager.windows
        op = plan.operation

        return {
            "window_available": windows.available,
            "window_operation": op,
            "verification_type": "dispatch_confirmed",
        }

    def _observe_browser_advanced(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check browser URL/title/state."""
        actual: Dict[str, Any] = {
            "browser_target": plan.target,
            "browser_observed": False,
        }

        try:
            title = self.os_manager.browser_get_title()
            actual["browser_page_title"] = title.get("title") if isinstance(title, dict) else None
        except Exception:
            actual["browser_page_title"] = None

        try:
            url = self.os_manager.browser_get_url()
            actual["browser_current_url"] = url.get("url") if isinstance(url, dict) else None
        except Exception:
            actual["browser_current_url"] = None

        try:
            tabs = self.os_manager.browser_get_tabs()
            actual["browser_tab_count"] = tabs.get("count") if isinstance(tabs, dict) else None
        except Exception:
            actual["browser_tab_count"] = None

        actual["browser_verified"] = bool(
            actual.get("browser_current_url")
            and actual.get("browser_page_title")
        )
        actual["browser_observed"] = actual["browser_verified"]
        actual["verification_type"] = "browser_state_query"
        return actual

    def _observe_filesystem_advanced(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check file content, not just existence."""
        op = plan.operation
        target = plan.target

        if not target:
            return {"observation_error": "No file target specified"}

        file_result = self.os_manager.inspect_file(target)
        identity = file_result.get("identity", {}) if isinstance(file_result, dict) else {}
        actual: Dict[str, Any] = {
            "file_exists": identity.get("exists"),
            "file_path": target,
            "file_size": file_result.get("size"),
            "file_type": file_result.get("type"),
            "modified": file_result.get("modified"),
        }

        if op == "file.create":
            expected_content = plan.parameters.get("content", "")
            if expected_content and file_result.get("exists"):
                try:
                    read_result = self.os_manager.read_file(target)
                    actual_content = read_result.get("content", "") if isinstance(read_result, dict) else ""
                    actual["content_matches"] = expected_content in actual_content
                    actual["content_preview"] = (
                        actual_content[:200] if isinstance(actual_content, str) else ""
                    )
                except Exception:
                    actual["content_matches"] = None

        elif op == "file.read":
            try:
                read_result = self.os_manager.read_file(target)
                actual["readable"] = True
                actual["content_preview"] = (
                    read_result.get("content", "")[:200]
                    if isinstance(read_result, dict)
                    else ""
                )
            except Exception:
                actual["readable"] = False

        elif op == "file.copy":
            dest = plan.parameters.get("destination", "")
            if dest:
                dest_result = self.os_manager.inspect_file(dest)
                actual["destination_exists"] = dest_result.get("exists", False)
                actual["destination_size"] = dest_result.get("size")

        actual["verification_type"] = "filesystem_query"
        return actual

    def _observe_spreadsheet(self, plan: ActionPlan) -> Dict[str, Any]:
        """Verify spreadsheet changes."""
        target = plan.target

        file_result = self.os_manager.inspect_file(target) if target else {}
        actual: Dict[str, Any] = {
            "spreadsheet_exists": file_result.get("exists", False),
            "spreadsheet_path": target,
            "sort_column": plan.parameters.get("column"),
            "descending": plan.parameters.get("descending", True),
        }

        if file_result.get("exists"):
            actual["file_size"] = file_result.get("size")
            actual["modified"] = file_result.get("modified")

        actual["verification_type"] = "filesystem_query"
        return actual

    def _observe_document(self, plan: ActionPlan) -> Dict[str, Any]:
        """Verify document creation."""
        target = plan.target

        file_result = self.os_manager.inspect_file(target) if target else {}
        actual: Dict[str, Any] = {
            "document_exists": file_result.get("exists", False),
            "document_path": target,
            "document_title": plan.parameters.get("title", target),
        }

        if file_result.get("exists"):
            actual["file_size"] = file_result.get("size")
            actual["modified"] = file_result.get("modified")

        actual["verification_type"] = "filesystem_query"
        return actual

    def _observe_notes(self, plan: ActionPlan) -> Dict[str, Any]:
        """Verify note creation."""
        op = plan.operation
        actual: Dict[str, Any] = {}

        if op == "notes.create":
            try:
                notes_result = self.os_manager.list_notes()
                note_count = notes_result.get("count", 0) if isinstance(notes_result, dict) else 0
                actual["notes_count"] = note_count
                actual["notes_available"] = True
            except Exception:
                actual["notes_available"] = False
            actual["note_text_preview"] = (plan.parameters.get("text", plan.target) or "")[:100]
        elif op == "notes.list":
            try:
                notes_result = self.os_manager.list_notes()
                actual["notes_count"] = notes_result.get("count", 0) if isinstance(notes_result, dict) else 0
                actual["notes_list"] = notes_result.get("notes", []) if isinstance(notes_result, dict) else []
                actual["notes_available"] = True
            except Exception:
                actual["notes_available"] = False

        actual["verification_type"] = "notes_query"
        return actual

    def _observe_network(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check network state."""
        op = plan.operation
        actual: Dict[str, Any] = {}

        if op == "web.research":
            actual["query"] = plan.parameters.get("query", plan.target)
            actual["max_results"] = plan.parameters.get("max_results", 5)
            actual["research_observed"] = True
        elif op == "network.list_wifi":
            try:
                wifi_result = self.os_manager.list_wifi()
                actual["wifi_available"] = wifi_result.get("success", False)
            except Exception:
                actual["wifi_available"] = False
        elif op == "network.connect_wifi":
            actual["ssid"] = plan.target
            actual["connection_observed"] = True

        actual["verification_type"] = "network_query"
        return actual

    def _observe_packages(self, plan: ActionPlan) -> Dict[str, Any]:
        """Check package manager state."""
        op = plan.operation
        packages = self.os_manager.packages

        actual: Dict[str, Any] = {
            "packages_available": True,
            "package_operation": op,
        }

        if op == "packages.search":
            actual["search_query"] = plan.parameters.get("query", plan.target)
        elif op == "packages.install":
            actual["package_id"] = plan.target
        elif op == "packages.uninstall":
            actual["package_id"] = plan.target

        actual["verification_type"] = "package_query"
        return actual

    # =========================================================
    # ENHANCED COMPARISON
    # =========================================================

    def _compare_states(
        self,
        expected: Dict[str, Any],
        actual: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Compare expected vs actual state for enhanced operations."""
        discrepancies: list[str] = []

        self._check_key(discrepancies, expected, actual, "application_running", "Application running state")
        self._check_key(discrepancies, expected, actual, "file_exists", "File existence")
        self._check_key(discrepancies, expected, actual, "folder_exists", "Folder existence")
        self._check_key(discrepancies, expected, actual, "clipboard_matches", "Clipboard content match")
        self._check_key(discrepancies, expected, actual, "content_matches", "File content match")
        self._check_key(discrepancies, expected, actual, "volume_changed", "Volume change")
        self._check_key(discrepancies, expected, actual, "brightness_changed", "Brightness change")
        self._check_key(discrepancies, expected, actual, "document_created", "Document creation")
        self._check_key(discrepancies, expected, actual, "note_created", "Note creation")
        self._check_key(discrepancies, expected, actual, "sort_applied", "Spreadsheet sort")
        self._check_key(discrepancies, expected, actual, "research_completed", "Web research")
        self._check_key(discrepancies, expected, actual, "media_dispatched", "Media dispatch")
        self._check_key(discrepancies, expected, actual, "package_installed", "Package install")
        self._check_key(discrepancies, expected, actual, "package_uninstalled", "Package uninstall")
        if expected.get("browser_opened") and actual.get("browser_verified") is not True:
            discrepancies.append("Browser page state was not independently observed")
        if expected.get("url"):
            actual_url = actual.get("browser_current_url")
            if not isinstance(actual_url, str) or not actual_url:
                discrepancies.append("Browser URL was not independently observed")
            elif not (
                actual_url.rstrip("/") == str(expected["url"]).rstrip("/")
                or actual_url.startswith(str(expected["url"]))
            ):
                discrepancies.append(
                    f"Browser URL mismatch: expected '{expected['url']}', got '{actual_url}'"
                )

        if "observation_error" in actual:
            discrepancies.append(f"Observation failed: {actual['observation_error']}")

        if discrepancies:
            return False, "; ".join(discrepancies)
        return True, None

    @staticmethod
    def _check_key(
        discrepancies: list[str],
        expected: Dict[str, Any],
        actual: Dict[str, Any],
        key: str,
        label: str,
    ) -> None:
        """Compare a single boolean key between expected and actual."""
        if key in expected:
            exp = expected[key]
            act = actual.get(key)
            if act is None or exp != act:
                discrepancies.append(f"{label} mismatch: expected {exp}, got {act}")

    # =========================================================
    # ENHANCED CHECKS & CONFIDENCE
    # =========================================================

    def _run_enhanced_checks(self, plan: ActionPlan) -> Dict[str, Any]:
        """Run additional verification checks beyond basic state."""
        checks: Dict[str, Any] = {}
        op = plan.operation

        if op == "file.create" and plan.target:
            try:
                from pathlib import Path
                p = Path(plan.target)
                checks["file_stat"] = {
                    "exists": p.exists(),
                    "is_file": p.is_file() if p.exists() else None,
                    "size_bytes": p.stat().st_size if p.exists() else None,
                }
            except Exception as exc:
                checks["file_stat"] = {"error": str(exc)}

        elif op == "clipboard.copy":
            try:
                paste = self.os_manager.clipboard.paste()
                checks["clipboard_readback"] = {
                    "has_content": not paste.get("empty", True),
                    "preview": paste.get("content_preview", ""),
                }
            except Exception as exc:
                checks["clipboard_readback"] = {"error": str(exc)}

        elif op.startswith("volume."):
            try:
                vol = self.os_manager.media.get_volume()
                checks["volume_readback"] = {
                    "percent": vol.get("volume_percent"),
                    "muted": vol.get("muted"),
                }
            except Exception as exc:
                checks["volume_readback"] = {"error": str(exc)}

        elif op.startswith("display."):
            try:
                bright = self.os_manager.display.get_brightness()
                checks["brightness_readback"] = {
                    "percent": bright.get("brightness_percent"),
                    "per_display": bright.get("per_display", []),
                }
            except Exception as exc:
                checks["brightness_readback"] = {"error": str(exc)}

        elif op == "notes.create":
            try:
                notes = self.os_manager.list_notes()
                checks["notes_verification"] = {
                    "count": notes.get("count", 0) if isinstance(notes, dict) else 0,
                }
            except Exception as exc:
                checks["notes_verification"] = {"error": str(exc)}

        elif op.startswith("browser."):
            try:
                page = self.os_manager.browser_verify()
                checks["browser_verification"] = {
                    "success": page.get("success", False) if isinstance(page, dict) else False,
                    "url": page.get("url") if isinstance(page, dict) else None,
                    "title": page.get("title") if isinstance(page, dict) else None,
                }
            except Exception as exc:
                checks["browser_verification"] = {"error": str(exc)}

        return checks

    @staticmethod
    def _compute_confidence(
        expected: Dict[str, Any],
        actual: Dict[str, Any],
        enhanced_checks: Dict[str, Any],
    ) -> float:
        """Compute a confidence score for the observation."""
        if not expected:
            return 0.5

        score = 1.0

        for key in ("file_exists", "folder_exists", "application_running"):
            if key in expected:
                exp_val = expected[key]
                act_val = actual.get(key)
                if act_val is not None and exp_val != act_val:
                    score -= 0.3

        if "observation_error" in actual:
            score -= 0.4

        if enhanced_checks:
            failed = sum(
                1 for v in enhanced_checks.values()
                if isinstance(v, dict) and "error" in v
            )
            score -= 0.1 * failed

        return max(0.0, min(1.0, score))
