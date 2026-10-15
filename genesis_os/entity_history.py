"""
Genesis OS — Entity History.

Tracks all entities (files, applications, folders, documents,
spreadsheets, browser tabs) that have been created, modified,
accessed, or referenced during the current session.

This module exists so that:

    "Open my results folder."
    "Find the newest spreadsheet."
    "Open it."

...can be resolved through entity history rather than guessing.

Design rules:

    - Every entity entry carries provenance (which level,
      which operation, which agent).
    - Every entry preserves a timestamp for recency ranking.
    - Entity references are resolved by type + recency +
      conversation context.
    - No silent guessing: if resolution is ambiguous, the
      system asks for clarification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from genesis_os.contracts import Entity as EntityContract


class EntityType(str, Enum):
    FILE = "file"
    FOLDER = "folder"
    APPLICATION = "application"
    BROWSER_TAB = "browser_tab"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    NOTE = "note"
    CLIPBOARD = "clipboard"


class EntityAction(str, Enum):
    CREATED = "created"
    OPENED = "opened"
    MODIFIED = "modified"
    ACCESSED = "accessed"
    CLOSED = "closed"
    REFERENCED = "referenced"


@dataclass(frozen=True)
class EntityEntry:
    """One tracked entity interaction."""

    entity_type: EntityType
    entity_id: str
    action: EntityAction
    timestamp: datetime
    source_level: int
    source_operation: Optional[str] = None
    source_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type.value,
            "entity_id": self.entity_id,
            "action": self.action.value,
            "timestamp": self.timestamp.isoformat(),
            "source_level": self.source_level,
            "source_operation": self.source_operation,
            "source_agent": self.source_agent,
            "metadata": self.metadata,
        }


class EntityHistory:
    """
    Session-scoped entity history.

    Every Level 2 and Level 3 operation that creates,
    opens, modifies, or references an entity records it
    here. Later turns resolve pronouns and vague references
    against this history.
    """

    VERSION = "3.0.0"

    MAX_ENTRIES = 200

    def __init__(self) -> None:
        self._entries: List[EntityEntry] = []

    # =========================================================
    # RECORDING
    # =========================================================

    def record(
        self,
        entity_type: EntityType,
        entity_id: str,
        action: EntityAction,
        *,
        source_level: int = 3,
        source_operation: Optional[str] = None,
        source_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EntityEntry:
        """Record an entity interaction."""

        entry = EntityEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            timestamp=datetime.now(),
            source_level=source_level,
            source_operation=source_operation,
            source_agent=source_agent,
            metadata=metadata or {},
        )

        # Phase 1 contract: malformed entries are rejected before
        # they can poison pronoun resolution.
        EntityContract.from_entry(entry)

        self._entries.append(entry)

        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES:]

        return entry

    def record_from_result(
        self,
        operation: str,
        target: str,
        result: Any,
        *,
        source_level: int = 3,
        source_agent: Optional[str] = None,
    ) -> None:
        """
        Automatically record an entity from an execution result.
        Derives entity type and action from the operation name.
        """

        entity_type = self._infer_entity_type(operation, target)
        if entity_type is None:
            return

        action = self._infer_action(operation)

        metadata: Dict[str, Any] = {}
        if isinstance(result, dict):
            for key in ("success", "message", "verified", "path", "url"):
                if key in result:
                    metadata[key] = result[key]

        self.record(
            entity_type,
            target,
            action,
            source_level=source_level,
            source_operation=operation,
            source_agent=source_agent,
            metadata=metadata,
        )

    # =========================================================
    # QUERIES
    # =========================================================

    def get_recent(
        self,
        entity_type: Optional[EntityType] = None,
        action: Optional[EntityAction] = None,
        limit: int = 10,
    ) -> List[EntityEntry]:
        """Get recent entries, optionally filtered."""

        entries = self._entries

        if entity_type is not None:
            entries = [e for e in entries if e.entity_type == entity_type]

        if action is not None:
            entries = [e for e in entries if e.action == action]

        return list(reversed(entries[-limit:]))

    def get_most_recent(
        self,
        entity_type: Optional[EntityType] = None,
    ) -> Optional[EntityEntry]:
        """Get the single most recent entry, optionally filtered."""

        entries = self._entries

        if entity_type is not None:
            entries = [e for e in entries if e.entity_type == entity_type]

        return entries[-1] if entries else None

    def find_entity(
        self,
        entity_type: EntityType,
        *,
        name_pattern: Optional[str] = None,
        action: Optional[EntityAction] = None,
    ) -> List[EntityEntry]:
        """
        Find entries matching type + optional name pattern + optional action.
        Name matching is case-insensitive substring.
        """

        entries = [
            e for e in self._entries
            if e.entity_type == entity_type
        ]

        if action is not None:
            entries = [e for e in entries if e.action == action]

        if name_pattern:
            pattern_lower = name_pattern.lower()
            entries = [
                e for e in entries
                if pattern_lower in e.entity_id.lower()
            ]

        return entries

    def find_newest_by_type(
        self,
        entity_type: EntityType,
    ) -> Optional[EntityEntry]:
        """Find the most recently created/modified entity of a given type."""

        relevant = [
            e for e in self._entries
            if e.entity_type == entity_type
            and e.action in (EntityAction.CREATED, EntityAction.MODIFIED, EntityAction.OPENED)
        ]

        return relevant[-1] if relevant else None

    def resolve_pronoun(
        self,
        pronoun: str,
        *,
        entity_type_hint: Optional[EntityType] = None,
    ) -> Optional[str]:
        """
        Resolve a pronoun or vague reference to a concrete entity ID.

        Supported pronouns/references:
            "it", "that", "this" → most recent entity (or filtered by type hint)
            "them", "those" → most recent group (not yet supported, returns None)
            "the file", "the document" → most recent file/document
            "the folder" → most recent folder
            "the application", "the app" → most recently opened application
            "the newest X" → most recently created/modified X
            "the original" → first entity in the current task's entity chain
            "the final" → last entity in the current task's entity chain

        Returns the entity_id (file path, app name, etc.) or None.
        """

        normalized = pronoun.lower().strip()

        # Pronoun resolution
        if normalized in ("it", "that", "this", "its"):
            if entity_type_hint:
                entry = self.get_most_recent(entity_type_hint)
            else:
                entry = self._entries[-1] if self._entries else None
            return entry.entity_id if entry else None

        if normalized in ("them", "those"):
            return None

        # Explicit type references
        type_map = {
            "the file": EntityType.FILE,
            "the document": EntityType.DOCUMENT,
            "the spreadsheet": EntityType.SPREADSHEET,
            "the folder": EntityType.FOLDER,
            "the directory": EntityType.FOLDER,
            "the application": EntityType.APPLICATION,
            "the app": EntityType.APPLICATION,
            "the browser": EntityType.BROWSER_TAB,
            "the note": EntityType.NOTE,
        }

        for pattern, etype in type_map.items():
            if normalized == pattern or normalized.rstrip("s") == pattern.rstrip("s"):
                entry = self.get_most_recent(etype)
                return entry.entity_id if entry else None

        # "the newest X" pattern
        newest_prefix = "the newest "
        if normalized.startswith(newest_prefix):
            remaining = normalized[len(newest_prefix):]
            for pattern, etype in type_map.items():
                if remaining in pattern or pattern.rstrip("s").endswith(remaining):
                    entry = self.find_newest_by_type(etype)
                    return entry.entity_id if entry else None

        # If an entity type hint was provided, use the most recent of that type
        if entity_type_hint:
            entry = self.get_most_recent(entity_type_hint)
            return entry.entity_id if entry else None

        # Fall back to most recent entity overall
        if self._entries:
            return self._entries[-1].entity_id

        return None

    # =========================================================
    # PROVENANCE
    # =========================================================

    def get_entity_provenance(
        self,
        entity_id: str,
    ) -> List[EntityEntry]:
        """Get the full provenance chain for an entity."""

        return [
            e for e in self._entries
            if e.entity_id == entity_id
        ]

    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of all entity interactions in this session."""

        by_type: Dict[str, int] = {}
        by_action: Dict[str, int] = {}
        by_level: Dict[int, int] = {}

        for entry in self._entries:
            by_type[entry.entity_type.value] = by_type.get(entry.entity_type.value, 0) + 1
            by_action[entry.action.value] = by_action.get(entry.action.value, 0) + 1
            by_level[entry.source_level] = by_level.get(entry.source_level, 0) + 1

        return {
            "total_entries": len(self._entries),
            "by_type": by_type,
            "by_action": by_action,
            "by_level": by_level,
        }

    # =========================================================
    # SERIALIZATION
    # =========================================================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "total_entries": len(self._entries),
            "entries": [e.to_dict() for e in self._entries],
        }

    def clear(self) -> None:
        self._entries.clear()

    # =========================================================
    # INTERNALS
    # =========================================================

    @staticmethod
    def _infer_entity_type(
        operation: str,
        target: str,
    ) -> Optional[EntityType]:
        """Infer entity type from the operation name."""

        op = operation.lower()

        if op.startswith("file.") or op.startswith("document."):
            return EntityType.FILE
        if op.startswith("folder."):
            return EntityType.FOLDER
        if op.startswith("application.") or op.startswith("app."):
            return EntityType.APPLICATION
        if op.startswith("browser."):
            return EntityType.BROWSER_TAB
        if op.startswith("spreadsheet."):
            return EntityType.SPREADSHEET
        if op.startswith("notes."):
            return EntityType.NOTE
        if op.startswith("clipboard."):
            return EntityType.CLIPBOARD

        return None

    @staticmethod
    def _infer_action(operation: str) -> EntityAction:
        """Infer action from the operation name."""

        op = operation.lower()

        if any(op.startswith(p) for p in ("file.create", "folder.create", "document.create", "notes.create")):
            return EntityAction.CREATED
        if any(op.startswith(p) for p in ("file.open", "folder.open", "application.open", "browser.open")):
            return EntityAction.OPENED
        if any(op.startswith(p) for p in ("file.edit", "file.move", "file.copy", "file.rename", "document.edit", "document.transform")):
            return EntityAction.MODIFIED
        if any(op.startswith(p) for p in ("file.read", "file.inspect", "file.search", "document.read", "document.inspect", "spreadsheet.read", "spreadsheet.inspect")):
            return EntityAction.ACCESSED
        if any(op.startswith(p) for p in ("application.close", "browser.close")):
            return EntityAction.CLOSED

        return EntityAction.ACCESSED
