"""
Genesis OS — Level 3 Session State Model.

Runtime OS session state tracking for context-aware execution:

    current application
    open applications
    known windows
    current browser
    current browser tab
    current folder
    recent files
    active document
    clipboard context
    current task
    completed subtasks
    failed subtasks

This is kept in a controlled runtime context rather than
unreliable conversational memory alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .action_plan import ActionPlan
from .action_result import ActionResult
from .os_manager import OSManager


@dataclass
class ApplicationState:
    """Tracked state of a running application."""
    name: str
    process_id: Optional[int] = None
    window_title: Optional[str] = None
    window_handle: Optional[int] = None
    is_focused: bool = False
    last_seen: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserState:
    """Tracked browser state."""
    browser_name: str
    current_url: Optional[str] = None
    current_tab_title: Optional[str] = None
    open_tabs: List[Dict[str, Any]] = field(default_factory=list)
    last_search_query: Optional[str] = None
    last_search_engine: Optional[str] = None
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class TaskState:
    """Tracked state of the current workflow task."""
    task_id: str
    objective: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    completed_steps: List[str] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    current_step: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionState:
    """
    Centralized OS session state model.
    
    Maintains awareness of the computer environment state
    for context resolution and intelligent execution.
    """

    VERSION = "3.0.0"

    def __init__(self, os_manager: Optional[OSManager] = None):
        self.os_manager = os_manager

        # Application state
        self._applications: Dict[str, ApplicationState] = {}
        self._current_application: Optional[str] = None

        # Browser state
        self._browser: Optional[BrowserState] = None

        # Filesystem state
        self._current_folder: Optional[str] = None
        self._recent_files: List[str] = []
        self._recent_folders: List[str] = []
        self._active_document: Optional[str] = None

        # Clipboard state
        self._clipboard_content: Optional[str] = None
        self._clipboard_updated: Optional[datetime] = None

        # Task state
        self._current_task: Optional[TaskState] = None
        self._task_history: List[TaskState] = []

        # General
        self._metadata: Dict[str, Any] = {"version": self.VERSION}

    # =========================================================
    # APPLICATION STATE
    # =========================================================

    def update_application(
        self,
        name: str,
        *,
        process_id: Optional[int] = None,
        window_title: Optional[str] = None,
        window_handle: Optional[int] = None,
        is_focused: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update or create application state."""
        app = self._applications.get(name)
        if app is None:
            app = ApplicationState(name=name)
            self._applications[name] = app

        if process_id is not None:
            app.process_id = process_id
        if window_title is not None:
            app.window_title = window_title
        if window_handle is not None:
            app.window_handle = window_handle
        app.is_focused = is_focused
        app.last_seen = datetime.now()
        if metadata:
            app.metadata.update(metadata)

        # Track as current if focused or explicitly opened
        if is_focused or self._current_application is None:
            self._current_application = name

    def get_application(self, name: str) -> Optional[ApplicationState]:
        """Get tracked application state."""
        return self._applications.get(name)

    def get_current_application(self) -> Optional[ApplicationState]:
        """Get the currently active application."""
        if self._current_application:
            return self._applications.get(self._current_application)
        return None

    def list_running_applications(self) -> List[ApplicationState]:
        """List all tracked running applications."""
        return list(self._applications.values())

    def mark_application_closed(self, name: str) -> None:
        """Mark an application as closed."""
        if name in self._applications:
            del self._applications[name]
        if self._current_application == name:
            # Fall back to another running app
            self._current_application = next(iter(self._applications), None)

    def refresh_from_system(self) -> None:
        """Refresh application state from actual system."""
        if not self.os_manager:
            return
        try:
            result = self.os_manager.list_processes(limit=100)
            for proc in result.get("processes", []):
                name = proc.get("name", "").lower()
                if name:
                    self.update_application(
                        name,
                        process_id=proc.get("pid"),
                        metadata=proc,
                    )
        except Exception:
            pass  # Silent failure for background refresh

    # =========================================================
    # BROWSER STATE
    # =========================================================

    def update_browser(
        self,
        browser_name: str,
        *,
        url: Optional[str] = None,
        tab_title: Optional[str] = None,
        search_query: Optional[str] = None,
        search_engine: Optional[str] = None,
    ) -> None:
        """Update browser state."""
        if self._browser is None or self._browser.browser_name != browser_name:
            self._browser = BrowserState(browser_name=browser_name)

        if url is not None:
            self._browser.current_url = url
        if tab_title is not None:
            self._browser.current_tab_title = tab_title
        if search_query is not None:
            self._browser.last_search_query = search_query
        if search_engine is not None:
            self._browser.last_search_engine = search_engine
        self._browser.last_updated = datetime.now()

    def get_browser(self) -> Optional[BrowserState]:
        """Get current browser state."""
        return self._browser

    # =========================================================
    # FILESYSTEM STATE
    # =========================================================

    def set_current_folder(self, path: str) -> None:
        """Set the current working folder."""
        self._current_folder = path
        if path not in self._recent_folders:
            self._recent_folders.insert(0, path)
            self._recent_folders = self._recent_folders[:20]

    def get_current_folder(self) -> Optional[str]:
        """Get the current working folder."""
        return self._current_folder

    def add_recent_file(self, path: str) -> None:
        """Add a file to recent files."""
        if path not in self._recent_files:
            self._recent_files.insert(0, path)
            self._recent_files = self._recent_files[:50]

    def get_recent_files(self, limit: int = 10) -> List[str]:
        """Get recent files."""
        return self._recent_files[:limit]

    def set_active_document(self, path: str) -> None:
        """Set the active document."""
        self._active_document = path
        self.add_recent_file(path)

    def get_active_document(self) -> Optional[str]:
        """Get the active document."""
        return self._active_document

    # =========================================================
    # CLIPBOARD STATE
    # =========================================================

    def set_clipboard(self, content: str) -> None:
        """Set clipboard content."""
        self._clipboard_content = content
        self._clipboard_updated = datetime.now()

    def get_clipboard(self) -> Optional[str]:
        """Get clipboard content."""
        return self._clipboard_content

    # =========================================================
    # TASK STATE
    # =========================================================

    def start_task(self, task_id: str, objective: str, steps: List[Dict[str, Any]]) -> None:
        """Start a new task."""
        self._current_task = TaskState(
            task_id=task_id,
            objective=objective,
            steps=steps,
        )
        self._task_history.append(self._current_task)

    def update_task_step(self, step_id: str, success: bool) -> None:
        """Update task step completion."""
        if self._current_task:
            if success:
                if step_id not in self._current_task.completed_steps:
                    self._current_task.completed_steps.append(step_id)
            else:
                if step_id not in self._current_task.failed_steps:
                    self._current_task.failed_steps.append(step_id)
            self._current_task.current_step = step_id

    def complete_task(self, success: bool = True) -> Optional[TaskState]:
        """Complete the current task and return it."""
        task = self._current_task
        if task:
            task.metadata["completed"] = True
            task.metadata["success"] = success
            task.metadata["completed_at"] = datetime.now().isoformat()
            self._current_task = None
        return task

    def get_current_task(self) -> Optional[TaskState]:
        """Get the current task."""
        return self._current_task

    # =========================================================
    # CONTEXT RESOLUTION HELPERS
    # =========================================================

    def resolve_reference(
        self,
        reference: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """
        Resolve natural language references to concrete values.
        
        References:
            "this", "that", "it" -> current task context
            "the file" -> active document
            "the folder" -> current folder
            "the browser" -> current browser
            "the application" -> current application
            "the previous file" -> recent files
            "the latest one" -> most recent file
            "the result" -> last task result
        """
        ref = reference.lower().strip()

        # Task context references
        if ref in ("this", "that", "it"):
            return self._resolve_task_context(context)

        # File/folder references
        if ref in ("the file", "the document", "it", "that file"):
            return self._active_document
        if ref in ("the folder", "the directory", "that folder"):
            return self._current_folder
        if ref in ("the previous file", "the last file"):
            return self._recent_files[0] if self._recent_files else None
        if ref in ("the latest file", "the newest file", "the latest one"):
            return self._recent_files[0] if self._recent_files else None

        # Application references
        if ref in ("the browser", "the web browser", "browser"):
            return self._browser
        if ref in ("the application", "the app", "that app", "the current app"):
            return self.get_current_application()
        if ref in ("the window", "that window"):
            app = self.get_current_application()
            return app.window_title if app else None

        # Clipboard
        if ref in ("the clipboard", "clipboard"):
            return self._clipboard_content

        # Task result
        if ref in ("the result", "the output", "the outcome"):
            if self._task_history:
                return self._task_history[-1].metadata.get("result")
            return None

        return None

    def _resolve_task_context(self, context: Optional[Dict[str, Any]]) -> Any:
        """Resolve 'this/that/it' from task context."""
        if context and "last_result" in context:
            return context["last_result"]
        if self._current_task and self._current_task.metadata.get("last_result"):
            return self._current_task.metadata["last_result"]
        return self._active_document or self._current_folder

    # =========================================================
    # SERIALIZATION
    # =========================================================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session state."""
        return {
            "version": self.VERSION,
            "current_application": self._current_application,
            "applications": {
                name: {
                    "name": app.name,
                    "process_id": app.process_id,
                    "window_title": app.window_title,
                    "window_handle": app.window_handle,
                    "is_focused": app.is_focused,
                    "last_seen": app.last_seen.isoformat(),
                    "metadata": app.metadata,
                }
                for name, app in self._applications.items()
            },
            "browser": {
                "browser_name": self._browser.browser_name,
                "current_url": self._browser.current_url,
                "current_tab_title": self._browser.current_tab_title,
                "open_tabs": self._browser.open_tabs,
                "last_search_query": self._browser.last_search_query,
                "last_search_engine": self._browser.last_search_engine,
                "last_updated": self._browser.last_updated.isoformat(),
            } if self._browser else None,
            "current_folder": self._current_folder,
            "recent_files": self._recent_files[:20],
            "recent_folders": self._recent_folders[:10],
            "active_document": self._active_document,
            "clipboard_updated": self._clipboard_updated.isoformat() if self._clipboard_updated else None,
            "current_task": {
                "task_id": self._current_task.task_id,
                "objective": self._current_task.objective,
                "completed_steps": self._current_task.completed_steps,
                "failed_steps": self._current_task.failed_steps,
                "current_step": self._current_task.current_step,
                "started_at": self._current_task.started_at.isoformat(),
                "metadata": self._current_task.metadata,
            } if self._current_task else None,
            "task_history_count": len(self._task_history),
            "metadata": self._metadata,
        }

    def clear(self) -> None:
        """Clear all session state."""
        self._applications.clear()
        self._current_application = None
        self._browser = None
        self._current_folder = None
        self._recent_files.clear()
        self._recent_folders.clear()
        self._active_document = None
        self._clipboard_content = None
        self._clipboard_updated = None
        self._current_task = None
        self._task_history.clear()
        self._metadata = {"version": self.VERSION}