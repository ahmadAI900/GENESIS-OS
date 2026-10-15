"""
Genesis OS — Level 3 Observation Loop.

Closed-loop execution verification:
    plan → execute → OBSERVE → compare → verify → recover/replan

This module observes actual system state after execution and compares
it to the expected state from the workflow step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable

from .action_plan import ActionPlan
from .action_result import ActionResult
from .os_manager import OSManager


@dataclass(frozen=True)
class ObservationResult:
    """Result of observing actual system state."""
    step_id: str
    operation: str
    target: str
    expected_state: Dict[str, Any]
    actual_state: Dict[str, Any]
    matches_expected: bool
    discrepancy: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "target": self.target,
            "expected_state": dict(self.expected_state),
            "actual_state": dict(self.actual_state),
            "matches_expected": self.matches_expected,
            "discrepancy": self.discrepancy,
            "metadata": dict(self.metadata),
        }


class ObservationLoop:
    """
    Closed-loop observation for workflow execution.
    
    After each step execution, this loop:
    1. Derives expected state from the ActionPlan
    2. Observes actual system state via OSManager
    3. Compares expected vs actual
    4. Returns structured observation for verification/recovery
    """

    VERSION = "3.0.0"

    def __init__(self, os_manager: OSManager):
        if os_manager is None:
            raise ValueError("ObservationLoop requires an OSManager.")
        self.os_manager = os_manager

    def observe(
        self,
        step_id: str,
        plan: ActionPlan,
        execution_result: ActionResult,
    ) -> ObservationResult:
        """
        Observe actual system state after step execution.
        
        Derives expected state from the ActionPlan and execution result,
        then queries the actual system state.
        """
        expected = self._derive_expected_state(plan, execution_result)
        actual = self._observe_actual_state(plan)
        matches, discrepancy = self._compare_states(expected, actual, plan)

        return ObservationResult(
            step_id=step_id,
            operation=plan.operation,
            target=plan.target or "",
            expected_state=expected,
            actual_state=actual,
            matches_expected=matches,
            discrepancy=discrepancy,
            metadata={
                "observation_version": self.VERSION,
                "execution_verified": execution_result.verified,
            },
        )

    def _derive_expected_state(
        self,
        plan: ActionPlan,
        execution_result: ActionResult,
    ) -> Dict[str, Any]:
        """Derive expected state from the action plan and execution result."""
        expected = {
            "operation": plan.operation,
            "target": plan.target,
            "application": plan.application,
        }

        op = plan.operation

        # Application operations
        if op == "application.open":
            expected.update({
                "application_running": True,
                "application_name": plan.application or plan.target,
            })
        elif op == "application.close":
            expected.update({
                "application_running": False,
                "application_name": plan.target or plan.application,
            })
        elif op == "application.inspect":
            expected.update({
                "application_exists": True,
                "application_name": plan.target or plan.application,
            })

        # File operations
        elif op == "file.create":
            expected.update({
                "file_exists": True,
                "file_path": plan.target,
                "content": plan.parameters.get("content", ""),
            })
        elif op == "file.delete":
            expected.update({
                "file_exists": False,
                "file_path": plan.target,
            })
        elif op == "file.move":
            expected.update({
                "file_exists": True,
                "file_path": plan.parameters.get("destination"),
                "source_gone": True,
                "source_path": plan.target,
            })
        elif op == "file.copy":
            expected.update({
                "file_exists": True,
                "file_path": plan.parameters.get("destination"),
                "source_exists": True,
                "source_path": plan.target,
            })
        elif op == "file.rename":
            expected.update({
                "file_exists": True,
                "file_path": plan.target,  # original path
                "new_name": plan.parameters.get("new_name"),
            })
        elif op in ("file.open", "file.read", "file.inspect"):
            expected.update({
                "file_exists": True,
                "file_path": plan.target,
            })

        # Folder operations
        elif op == "folder.create":
            expected.update({
                "folder_exists": True,
                "folder_path": plan.target,
            })
        elif op == "folder.delete":
            expected.update({
                "folder_exists": False,
                "folder_path": plan.target,
            })
        elif op == "folder.open":
            expected.update({
                "folder_exists": True,
                "folder_path": plan.target,
            })
        elif op in ("folder.move", "folder.rename"):
            expected.update({
                "folder_exists": True,
                "folder_path": plan.parameters.get("destination") or plan.parameters.get("new_name"),
            })

        # Browser operations
        elif op == "browser.open_url":
            expected.update({
                "browser_opened": True,
                "url": plan.target,
            })
        elif op == "browser.search":
            expected.update({
                "browser_opened": True,
                "search_query": plan.parameters.get("query", plan.target),
                "engine": plan.parameters.get("engine", "google"),
            })
        elif op == "browser.click":
            expected.update({
                "element_clicked": True,
                "selector": plan.target,
            })
        elif op == "browser.type":
            expected.update({
                "text_typed": True,
                "selector": plan.target,
                "text": plan.parameters.get("text", ""),
            })
        elif op == "browser.scroll":
            expected.update({
                "page_scrolled": True,
                "direction": plan.parameters.get("direction", "down"),
                "amount": plan.parameters.get("amount", 3),
            })
        elif op == "browser.select":
            expected.update({
                "option_selected": True,
                "selector": plan.target,
                "selected_value": plan.parameters.get("value"),
                "selected_label": plan.parameters.get("label"),
                "selected_index": plan.parameters.get("index"),
            })
        elif op == "browser.download":
            expected.update({
                "file_downloaded": True,
                "url": plan.target,
                "save_path": plan.parameters.get("save_path"),
            })
        elif op == "browser.upload":
            expected.update({
                "file_uploaded": True,
                "selector": plan.target,
                "file_path": plan.parameters.get("file_path"),
            })
        elif op == "browser.find":
            expected.update({
                "text_found": True,
                "search_text": plan.target,
            })
        elif op == "browser.extract":
            expected.update({
                "text_extracted": True,
                "selector": plan.target,
            })

        # System operations
        elif op == "system.open_settings":
            expected.update({
                "settings_opened": True,
                "settings_target": plan.target,
            })

        # Merge execution evidence into expected state
        if execution_result.execution:
            expected["execution_evidence"] = execution_result.execution
        if execution_result.verification:
            expected["verification_evidence"] = execution_result.verification

        return expected

    def _observe_actual_state(self, plan: ActionPlan) -> Dict[str, Any]:
        """Query actual system state via OSManager."""
        actual = {}
        op = plan.operation
        target = plan.target

        try:
            # Application state observation
            if op.startswith("application."):
                app_name = plan.application or target
                if app_name:
                    result = self.os_manager.inspect_application(app_name)
                    actual.update({
                        "application_running": result.get("running"),
                        "application_exists": result.get("available"),
                        "application_name": result.get("application", app_name),
                        "process_id": result.get("process_id"),
                        "window_title": result.get("window_title"),
                    })

            # File state observation
            elif op.startswith("file."):
                if target:
                    result = self.os_manager.inspect_file(target)
                    identity = result.get("identity", {}) if isinstance(result, dict) else {}
                    actual.update({
                        "file_exists": identity.get("exists"),
                        "file_path": target,
                        "file_size": result.get("size"),
                        "file_type": result.get("type"),
                        "modified": result.get("modified"),
                    })

            # Folder state observation
            elif op.startswith("folder."):
                if target:
                    result = self.os_manager.inspect_folder(target)
                    actual.update({
                        "folder_exists": bool(result.get("success")) if isinstance(result, dict) else False,
                        "folder_path": target,
                        "item_count": result.get("item_count"),
                    })

            # Process observation
            elif op == "process.inspect":
                if target:
                    result = self.os_manager.inspect_process(target)
                    actual.update({
                        "process_running": result.get("running", False),
                        "process_name": target,
                        "pid": result.get("pid"),
                        "cpu_percent": result.get("cpu_percent"),
                        "memory_mb": result.get("memory_mb"),
                    })

            # Browser state observation
            elif op.startswith("browser."):
                session_id = plan.parameters.get("session_id", "default")
                actual["browser_operation"] = op
                actual["browser_session"] = session_id

                if target:
                    actual.update({
                        "browser_target": target,
                        "browser_observed": True,
                    })

                try:
                    url_result = self.os_manager.browser_get_url(session_id=session_id)
                    if (
                        isinstance(url_result, dict)
                        and url_result.get("success")
                        and url_result.get("url")
                    ):
                        actual["browser_page_url"] = url_result["url"]

                    title_result = self.os_manager.browser_get_title(session_id=session_id)
                    if (
                        isinstance(title_result, dict)
                        and title_result.get("success")
                        and title_result.get("title")
                    ):
                        actual["browser_page_title"] = title_result["title"]

                    actual["browser_verified"] = bool(
                        actual.get("browser_page_url")
                        and actual.get("browser_page_title")
                    )
                except Exception:
                    actual["browser_verified"] = False

                if op == "browser.select":
                    actual["select_performed"] = False
                    actual["select_observation"] = "not_independently_observed"
                elif op == "browser.download":
                    save_path = plan.parameters.get("save_path")
                    if save_path:
                        import os
                        actual["download_file_exists"] = os.path.exists(save_path)
                        actual["download_file_size"] = os.path.getsize(save_path) if os.path.exists(save_path) else 0
                    actual["download_performed"] = False
                    actual["download_observation"] = "no baseline was captured"
                elif op == "browser.upload":
                    file_path = plan.parameters.get("file_path")
                    if file_path:
                        import os
                        actual["upload_source_exists"] = os.path.exists(file_path)
                    actual["upload_performed"] = False
                    actual["upload_observation"] = "remote completion is not observable"
                elif op == "browser.click":
                    actual["click_performed"] = False
                    actual["click_observation"] = "no click postcondition was observed"
                elif op == "browser.type":
                    actual["type_performed"] = False
                    actual["type_observation"] = "input value was not independently read back"
                elif op == "browser.scroll":
                    actual["scroll_performed"] = False
                    actual["scroll_observation"] = "scroll offset was not independently read back"
                elif op == "browser.find":
                    result = self.os_manager.browser_find(
                        target,
                        session_id=session_id,
                    )
                    actual["find_count"] = result.get("count") if isinstance(result, dict) else None
                elif op == "browser.extract":
                    result = self.os_manager.browser_extract(session_id=session_id)
                    actual["extracted_text"] = result.get("text") if isinstance(result, dict) else None

        except Exception as exc:
            actual["observation_error"] = str(exc)

        return actual

    def _compare_states(
        self,
        expected: Dict[str, Any],
        actual: Dict[str, Any],
        plan: ActionPlan,
    ) -> tuple[bool, Optional[str]]:
        """Compare expected vs actual state."""
        discrepancies = []

        op = plan.operation

        # Application running state
        if "application_running" in expected:
            exp = expected["application_running"]
            act = actual.get("application_running")
            if act is None or exp != act:
                discrepancies.append(
                    f"Application running state mismatch: expected {exp}, got {act}"
                )

        if "application_exists" in expected:
            exp = expected["application_exists"]
            act = actual.get("application_exists")
            if act is None or exp != act:
                discrepancies.append(
                    f"Application existence mismatch: expected {exp}, got {act}"
                )

        if "file_exists" in expected:
            exp = expected["file_exists"]
            act = actual.get("file_exists")
            if act is None or exp != act:
                discrepancies.append(
                    f"File existence mismatch: expected {exp}, got {act}"
                )

        if "content" in expected and expected.get("file_path"):
            try:
                from pathlib import Path
                content = Path(expected["file_path"]).read_text(encoding="utf-8")
                if content != expected["content"]:
                    discrepancies.append("File content did not match the requested content")
            except Exception as exc:
                discrepancies.append(f"File content could not be read: {exc}")

        if "folder_exists" in expected:
            exp = expected["folder_exists"]
            act = actual.get("folder_exists")
            if act is None or exp != act:
                discrepancies.append(
                    f"Folder existence mismatch: expected {exp}, got {act}"
                )

        # Source file gone (for move)
        if expected.get("source_gone"):
            source_path = expected.get("source_path")
            if source_path:
                try:
                    from pathlib import Path
                    if Path(source_path).exists():
                        discrepancies.append(f"Source file still exists: {source_path}")
                except Exception as exc:
                    discrepancies.append(f"Source removal could not be checked: {exc}")

        # Destination file exists (for move/copy)
        if expected.get("file_path") and op in ("file.move", "file.copy"):
            dest = expected.get("file_path")
            if dest:
                try:
                    from pathlib import Path
                    if not Path(dest).exists():
                        discrepancies.append(f"Destination file does not exist: {dest}")
                except Exception as exc:
                    discrepancies.append(f"Destination could not be checked: {exc}")

        # New name for rename
        if "new_name" in expected and expected["new_name"]:
            # Check if renamed file exists
            target = plan.target
            new_name = expected["new_name"]
            if target:
                try:
                    from pathlib import Path
                    parent = Path(target).parent
                    new_path = parent / new_name
                    if not new_path.exists():
                        discrepancies.append(f"Renamed file does not exist: {new_path}")
                except Exception as exc:
                    discrepancies.append(f"Renamed path could not be checked: {exc}")

        # Browser operation verification
        if plan.operation.startswith("browser."):
            if expected.get("url") and expected["url"] not in actual.get("browser_page_url", ""):
                discrepancies.append(
                    f"Browser URL mismatch: expected '{expected['url']}' in '{actual.get('browser_page_url')}'"
                )
            if expected.get("browser_opened") and not actual.get("browser_verified"):
                discrepancies.append("Browser page state was not independently observed")
            if expected.get("option_selected") and actual.get("select_performed") is not True:
                discrepancies.append("Select operation was not observed")
            if expected.get("file_downloaded") and actual.get("download_performed") is not True:
                discrepancies.append("Download completion was not independently observed")
            if expected.get("file_uploaded") and actual.get("upload_performed") is not True:
                discrepancies.append("Upload completion was not independently observed")
            if expected.get("element_clicked") and actual.get("click_performed") is not True:
                discrepancies.append("Click operation was not observed")
            if expected.get("text_typed") and actual.get("type_performed") is not True:
                discrepancies.append("Type operation was not observed")
            if expected.get("page_scrolled") and actual.get("scroll_performed") is not True:
                discrepancies.append("Scroll operation was not observed")
            if expected.get("text_found") and not (actual.get("find_count") or 0):
                discrepancies.append("Search text was not found")
            if expected.get("text_extracted") and not actual.get("extracted_text"):
                discrepancies.append("Text extraction was not observed")

        # Observation error
        if "observation_error" in actual:
            discrepancies.append(f"Observation failed: {actual['observation_error']}")

        if discrepancies:
            return False, "; ".join(discrepancies)

        return True, None


class CapabilityObserver:
    """
    Maps operations to observation functions for extensibility.
    """

    def __init__(self, os_manager: OSManager):
        self.os_manager = os_manager
        self._observers: Dict[str, Callable[[ActionPlan], Dict[str, Any]]] = {}
        self._register_default_observers()

    def _register_default_observers(self) -> None:
        """Register default observation functions."""
        self._observers.update({
            "application.open": self._observe_app_open,
            "application.close": self._observe_app_close,
            "application.inspect": self._observe_app_inspect,
            "file.create": self._observe_file_create,
            "file.delete": self._observe_file_delete,
            "file.move": self._observe_file_move,
            "file.copy": self._observe_file_copy,
            "file.rename": self._observe_file_rename,
            "file.open": self._observe_file_open,
            "file.read": self._observe_file_read,
            "file.inspect": self._observe_file_inspect,
            "folder.create": self._observe_folder_create,
            "folder.delete": self._observe_folder_delete,
            "folder.open": self._observe_folder_open,
            "folder.move": self._observe_folder_move,
            "folder.rename": self._observe_folder_rename,
            "browser.open_url": self._observe_browser_open_url,
            "browser.search": self._observe_browser_search,
            "browser.click": self._observe_browser_click,
            "browser.type": self._observe_browser_type,
            "browser.scroll": self._observe_browser_scroll,
            "browser.select": self._observe_browser_select,
            "browser.download": self._observe_browser_download,
            "browser.upload": self._observe_browser_upload,
            "browser.find": self._observe_browser_find,
            "browser.extract": self._observe_browser_extract,
        })

    def register_observer(self, operation: str, observer: Callable[[ActionPlan], Dict[str, Any]]) -> None:
        """Register a custom observer for an operation."""
        self._observers[operation] = observer

    def observe(self, plan: ActionPlan) -> Dict[str, Any]:
        """Run the appropriate observer for the plan's operation."""
        observer = self._observers.get(plan.operation)
        if observer:
            return observer(plan)
        return {"observation_error": f"No observer for operation: {plan.operation}"}

    # Application observers
    def _observe_app_open(self, plan: ActionPlan) -> Dict[str, Any]:
        app = plan.target or plan.application
        if not app:
            return {"observation_error": "No application target"}
        return self.os_manager.inspect_application(app)

    def _observe_app_close(self, plan: ActionPlan) -> Dict[str, Any]:
        app = plan.target or plan.application
        if not app:
            return {"observation_error": "No application target"}
        return self.os_manager.inspect_application(app)

    def _observe_app_inspect(self, plan: ActionPlan) -> Dict[str, Any]:
        app = plan.target or plan.application
        if not app:
            return {"observation_error": "No application target"}
        return self.os_manager.inspect_application(app)

    # File observers
    def _observe_file_create(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_file(plan.target)

    def _observe_file_delete(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_file(plan.target)

    def _observe_file_move(self, plan: ActionPlan) -> Dict[str, Any]:
        result = self.os_manager.inspect_file(plan.parameters.get("destination", ""))
        result["source_checked"] = self.os_manager.inspect_file(plan.target).get("exists", False)
        return result

    def _observe_file_copy(self, plan: ActionPlan) -> Dict[str, Any]:
        result = self.os_manager.inspect_file(plan.parameters.get("destination", ""))
        result["source_exists"] = self.os_manager.inspect_file(plan.target).get("exists", False)
        return result

    def _observe_file_rename(self, plan: ActionPlan) -> Dict[str, Any]:
        new_name = plan.parameters.get("new_name")
        if not new_name:
            return {"observation_error": "No new_name parameter"}
        from pathlib import Path
        new_path = Path(plan.target).parent / new_name
        return self.os_manager.inspect_file(str(new_path))

    def _observe_file_open(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_file(plan.target)

    def _observe_file_read(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_file(plan.target)

    def _observe_file_inspect(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_file(plan.target)

    # Folder observers
    def _observe_folder_create(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_folder(plan.target)

    def _observe_folder_delete(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_folder(plan.target)

    def _observe_folder_open(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_folder(plan.target)

    def _observe_folder_move(self, plan: ActionPlan) -> Dict[str, Any]:
        return self.os_manager.inspect_folder(plan.parameters.get("destination", ""))

    def _observe_folder_rename(self, plan: ActionPlan) -> Dict[str, Any]:
        new_name = plan.parameters.get("new_name")
        if not new_name:
            return {"observation_error": "No new_name parameter"}
        from pathlib import Path
        new_path = Path(plan.target).parent / new_name
        return self.os_manager.inspect_folder(str(new_path))

    # Browser observers
    def _observe_browser_open_url(self, plan: ActionPlan) -> Dict[str, Any]:
        result = self.os_manager.browser_get_page_state(
            plan.parameters.get("session_id", "default")
        )
        url = result.get("url") if isinstance(result, dict) else None
        title = result.get("title") if isinstance(result, dict) else None
        return {
            "url_observed": url,
            "title_observed": title,
            "browser_opened": bool(url and title),
        }

    def _observe_browser_search(self, plan: ActionPlan) -> Dict[str, Any]:
        result = self.os_manager.browser_get_page_state(
            plan.parameters.get("session_id", "default")
        )
        url = result.get("url") if isinstance(result, dict) else None
        title = result.get("title") if isinstance(result, dict) else None
        return {
            "search_query": plan.parameters.get("query", plan.target),
            "engine": plan.parameters.get("engine", "google"),
            "url_observed": url,
            "title_observed": title,
            "browser_opened": bool(url and title),
        }

    def _observe_browser_click(self, plan: ActionPlan) -> Dict[str, Any]:
        return {
            "click_performed": False,
            "selector": plan.target,
            "click_observation": "click postcondition is not independently observable",
        }

    def _observe_browser_type(self, plan: ActionPlan) -> Dict[str, Any]:
        return {
            "type_performed": False,
            "selector": plan.target,
            "type_observation": "input value is not independently observable here",
        }

    def _observe_browser_scroll(self, plan: ActionPlan) -> Dict[str, Any]:
        return {
            "scroll_performed": False,
            "scroll_observation": "scroll offset is not independently observable here",
        }

    def _observe_browser_select(self, plan: ActionPlan) -> Dict[str, Any]:
        return {
            "select_performed": False,
            "select_observation": "selected option is not independently observable here",
        }

    def _observe_browser_download(self, plan: ActionPlan) -> Dict[str, Any]:
        save_path = plan.parameters.get("save_path")
        file_exists = False
        file_size = 0
        if save_path:
            import os
            file_exists = os.path.exists(save_path)
            file_size = os.path.getsize(save_path) if file_exists else 0
        return {
            "download_performed": False,
            "url": plan.target,
            "save_path": save_path,
            "file_exists": file_exists,
            "file_size": file_size,
            "download_observation": "no pre-dispatch baseline was available",
        }

    def _observe_browser_upload(self, plan: ActionPlan) -> Dict[str, Any]:
        file_path = plan.parameters.get("file_path")
        source_exists = False
        if file_path:
            import os
            source_exists = os.path.exists(file_path)
        return {
            "upload_performed": False,
            "selector": plan.target,
            "file_path": file_path,
            "source_exists": source_exists,
            "upload_observation": "remote completion is not independently observable",
        }

    def _observe_browser_find(self, plan: ActionPlan) -> Dict[str, Any]:
        result = self.os_manager.browser_find(
            plan.target,
            session_id=plan.parameters.get("session_id", "default"),
        )
        return {
            "find_count": result.get("count") if isinstance(result, dict) else None,
            "text": plan.target,
        }

    def _observe_browser_extract(self, plan: ActionPlan) -> Dict[str, Any]:
        result = self.os_manager.browser_extract(
            plan.target,
            session_id=plan.parameters.get("session_id", "default"),
        )
        return {
            "extracted_text": result.get("text") if isinstance(result, dict) else None,
            "selector": plan.target,
        }