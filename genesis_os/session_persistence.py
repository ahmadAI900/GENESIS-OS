"""
Genesis OS — Level 3 Session State Persistence.

JSON-based persistence layer for SessionState, enabling session
state to survive across process restarts. Implements atomic writes
and non-blocking auto-save for reliability.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .session_state import (
    ApplicationState,
    BrowserState,
    SessionState,
    TaskState,
)


class SessionPersistence:
    """JSON-based persistence for SessionState."""

    DEFAULT_STORAGE_DIR = Path.home() / ".genesis" / "session"
    SESSION_FILE = "session_state.json"

    def __init__(self, storage_dir: Optional[Path] = None):
        self._storage_dir = storage_dir or self.DEFAULT_STORAGE_DIR
        self._ensure_storage_dir()

    def save(self, session_state: SessionState) -> bool:
        """Serialize session state to JSON with atomic write."""
        try:
            data = self._serialize_session(session_state)
            # Phase 1 contract: malformed snapshots never reach disk.
            from genesis_os.contracts import Session as SessionContract
            SessionContract.from_serialized(data)
            session_file = self.get_session_file()
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(self._storage_dir),
                suffix=".tmp",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                # Atomic rename
                os.replace(tmp_path, str(session_file))
                return True
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            return False

    def load(self) -> Optional[dict]:
        """Load persisted session state."""
        session_file = self.get_session_file()
        if not session_file.exists():
            return None
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self._deserialize_session(data)
        except (json.JSONDecodeError, OSError):
            return None

    def clear(self) -> bool:
        """Clear persisted state."""
        session_file = self.get_session_file()
        if session_file.exists():
            try:
                session_file.unlink()
                return True
            except OSError:
                return False
        return True

    def backup(self) -> Path:
        """Create timestamped backup of current session file."""
        session_file = self.get_session_file()
        if not session_file.exists():
            raise FileNotFoundError("No session file to backup")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self._storage_dir / f"session_state_{timestamp}.json"
        backup_file.write_bytes(session_file.read_bytes())
        return backup_file

    def get_session_file(self) -> Path:
        """Return current session file path."""
        return self._storage_dir / self.SESSION_FILE

    def _serialize_session(self, session_state: SessionState) -> dict:
        """Convert SessionState to JSON-safe dict."""
        # SessionState already has to_dict() that handles most serialization
        data = session_state.to_dict()

        # Ensure task_history is serialized (to_dict only includes count)
        data["task_history"] = [
            {
                "task_id": t.task_id,
                "objective": t.objective,
                "steps": t.steps,
                "completed_steps": t.completed_steps,
                "failed_steps": t.failed_steps,
                "current_step": t.current_step,
                "started_at": t.started_at.isoformat(),
                "metadata": t.metadata,
            }
            for t in session_state._task_history
        ]

        # Serialize clipboard content
        data["clipboard_content"] = session_state._clipboard_content

        # Add persistence metadata
        data["persisted_at"] = datetime.now().isoformat()

        return data

    def _deserialize_session(self, data: dict) -> dict:
        """Convert dict back to session state fields."""
        # Parse datetime strings back to datetime objects
        for app_data in data.get("applications", {}).values():
            if "last_seen" in app_data:
                try:
                    app_data["last_seen"] = datetime.fromisoformat(app_data["last_seen"])
                except (ValueError, TypeError):
                    app_data["last_seen"] = datetime.now()

        browser_data = data.get("browser")
        if browser_data and "last_updated" in browser_data:
            try:
                browser_data["last_updated"] = datetime.fromisoformat(browser_data["last_updated"])
            except (ValueError, TypeError):
                browser_data["last_updated"] = datetime.now()

        if "clipboard_updated" in data and data["clipboard_updated"]:
            try:
                data["clipboard_updated"] = datetime.fromisoformat(data["clipboard_updated"])
            except (ValueError, TypeError):
                data["clipboard_updated"] = None

        # Parse task history datetimes
        for task_data in data.get("task_history", []):
            if "started_at" in task_data:
                try:
                    task_data["started_at"] = datetime.fromisoformat(task_data["started_at"])
                except (ValueError, TypeError):
                    task_data["started_at"] = datetime.now()

        return data

    def _ensure_storage_dir(self) -> None:
        """Create storage directory if needed."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)


class PersistentSessionState:
    """Extends SessionState with persistence via auto-save."""

    def __init__(
        self,
        session_state: SessionState,
        persistence: Optional[SessionPersistence] = None,
    ):
        self._session = session_state
        self._persistence = persistence or SessionPersistence()

    @property
    def session(self) -> SessionState:
        """Access the underlying SessionState."""
        return self._session

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
        """Update application and auto-save."""
        self._session.update_application(
            name,
            process_id=process_id,
            window_title=window_title,
            window_handle=window_handle,
            is_focused=is_focused,
            metadata=metadata,
        )
        self._auto_save()

    def mark_application_closed(self, name: str) -> None:
        """Mark application closed and auto-save."""
        self._session.mark_application_closed(name)
        self._auto_save()

    def update_browser(
        self,
        browser_name: str,
        *,
        url: Optional[str] = None,
        tab_title: Optional[str] = None,
        search_query: Optional[str] = None,
        search_engine: Optional[str] = None,
    ) -> None:
        """Update browser state and auto-save."""
        self._session.update_browser(
            browser_name,
            url=url,
            tab_title=tab_title,
            search_query=search_query,
            search_engine=search_engine,
        )
        self._auto_save()

    def set_current_folder(self, path: str) -> None:
        """Set current folder and auto-save."""
        self._session.set_current_folder(path)
        self._auto_save()

    def add_recent_file(self, path: str) -> None:
        """Add recent file and auto-save."""
        self._session.add_recent_file(path)
        self._auto_save()

    def set_active_document(self, path: str) -> None:
        """Set active document and auto-save."""
        self._session.set_active_document(path)
        self._auto_save()

    def set_clipboard(self, content: str) -> None:
        """Set clipboard content and auto-save."""
        self._session.set_clipboard(content)
        self._auto_save()

    def start_task(
        self, task_id: str, objective: str, steps: List[Dict[str, Any]]
    ) -> None:
        """Start task and auto-save."""
        self._session.start_task(task_id, objective, steps)
        self._auto_save()

    def complete_task(self, success: bool = True) -> Optional[TaskState]:
        """Complete task and auto-save."""
        task = self._session.complete_task(success)
        self._auto_save()
        return task

    def restore(self) -> bool:
        """Load and apply persisted state."""
        data = self._persistence.load()
        if data is None:
            return False

        # Restore applications
        self._session._applications.clear()
        for name, app_data in data.get("applications", {}).items():
            self._session._applications[name] = ApplicationState(
                name=app_data["name"],
                process_id=app_data.get("process_id"),
                window_title=app_data.get("window_title"),
                window_handle=app_data.get("window_handle"),
                is_focused=app_data.get("is_focused", False),
                last_seen=app_data.get("last_seen", datetime.now()),
                metadata=app_data.get("metadata", {}),
            )
        self._session._current_application = data.get("current_application")

        # Restore browser
        browser_data = data.get("browser")
        if browser_data:
            self._session._browser = BrowserState(
                browser_name=browser_data["browser_name"],
                current_url=browser_data.get("current_url"),
                current_tab_title=browser_data.get("current_tab_title"),
                open_tabs=browser_data.get("open_tabs", []),
                last_search_query=browser_data.get("last_search_query"),
                last_search_engine=browser_data.get("last_search_engine"),
                last_updated=browser_data.get("last_updated", datetime.now()),
            )
        else:
            self._session._browser = None

        # Restore filesystem state
        self._session._current_folder = data.get("current_folder")
        self._session._recent_files = data.get("recent_files", [])
        self._session._recent_folders = data.get("recent_folders", [])
        self._session._active_document = data.get("active_document")

        # Restore clipboard
        self._session._clipboard_content = data.get("clipboard_content")
        self._session._clipboard_updated = data.get("clipboard_updated")

        # Restore task state
        task_data = data.get("current_task")
        if task_data:
            self._session._current_task = TaskState(
                task_id=task_data["task_id"],
                objective=task_data["objective"],
                steps=task_data.get("steps", []),
                completed_steps=task_data.get("completed_steps", []),
                failed_steps=task_data.get("failed_steps", []),
                current_step=task_data.get("current_step"),
                started_at=task_data.get("started_at", datetime.now()),
                metadata=task_data.get("metadata", {}),
            )
        else:
            self._session._current_task = None

        # Restore task history
        self._session._task_history = []
        for task_data in data.get("task_history", []):
            self._session._task_history.append(
                TaskState(
                    task_id=task_data["task_id"],
                    objective=task_data["objective"],
                    steps=task_data.get("steps", []),
                    completed_steps=task_data.get("completed_steps", []),
                    failed_steps=task_data.get("failed_steps", []),
                    current_step=task_data.get("current_step"),
                    started_at=task_data.get("started_at", datetime.now()),
                    metadata=task_data.get("metadata", {}),
                )
            )

        # Restore metadata
        self._session._metadata = data.get("metadata", {"version": SessionState.VERSION})

        return True

    def _auto_save(self) -> None:
        """Internal save with error swallowing (non-blocking)."""
        try:
            self._persistence.save(self._session)
        except Exception:
            pass  # Non-blocking: swallow errors
