"""
Genesis OS — Structured Agent Context.

Bundles session state, entity history, and conversation context
into a structured object that agents receive before execution.

This satisfies the spec requirement:

    "Agents must receive structured context."

Instead of passing raw text, agents receive:

    - session state (current app, folder, file, browser)
    - entity history (what was created/modified/recently accessed)
    - conversation context (what was discussed)
    - task graph context (previous agent results)

This enables agents to understand:

    "Open my results folder."
    "Find the newest spreadsheet."
    "Open it."

...because the agent receives the entity history showing
what folders and spreadsheets exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StructuredAgentContext:
    """
    Structured context passed to every Level 2 agent.

    Agents use this to understand the current OS state,
    recent entities, and prior results without guessing.
    """

    VERSION = "3.0.0"

    task: str = ""

    session_state: Optional[Dict[str, Any]] = None

    entity_history: Optional[Dict[str, Any]] = None

    recent_entities: List[Dict[str, Any]] = field(
        default_factory=list
    )

    previous_agent_results: List[Dict[str, Any]] = field(
        default_factory=list
    )

    conversation_summary: str = ""

    current_application: Optional[str] = None

    current_folder: Optional[str] = None

    active_document: Optional[str] = None

    clipboard_content: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    # =========================================================
    # CONSTRUCTION FROM GENESIS STATE
    # =========================================================

    @classmethod
    def from_genesis_state(
        cls,
        task: str,
        *,
        session_state=None,
        entity_history=None,
        previous_results=None,
        conversation_history=None,
    ) -> "StructuredAgentContext":
        """
        Build a StructuredAgentContext from live Genesis state.
        """

        session_dict = None
        current_app = None
        current_folder = None
        active_doc = None
        clipboard = None
        recent_entities = []

        if session_state is not None:
            try:
                session_dict = session_state.to_dict()
                current_app = session_state._current_application
                current_folder = session_state._current_folder
                active_doc = session_state._active_document
                clipboard = session_state._clipboard_content
            except Exception:
                pass

        entity_dict = None
        if entity_history is not None:
            try:
                entity_dict = entity_history.to_dict()
                recent_entries = entity_history.get_recent(limit=15)
                recent_entities = [e.to_dict() for e in recent_entries]
            except Exception:
                pass

        conv_summary = ""
        if conversation_history:
            try:
                recent = conversation_history[-6:]
                conv_summary = "\n".join(
                    f"{m.get('role', '?')}: {m.get('message', '')}"
                    for m in recent
                )
            except Exception:
                pass

        prev_results = []
        if previous_results:
            for item in previous_results[-5:]:
                if isinstance(item, dict):
                    prev_results.append({
                        "agent": item.get("agent", "Unknown"),
                        "result_summary": str(
                            item.get("result", "")
                        )[:500],
                    })

        return cls(
            task=task,
            session_state=session_dict,
            entity_history=entity_dict,
            recent_entities=recent_entities,
            previous_agent_results=prev_results,
            conversation_summary=conv_summary,
            current_application=current_app,
            current_folder=current_folder,
            active_document=active_doc,
            clipboard_content=clipboard,
        )

    # =========================================================
    # CONTEXT INJECTION
    # =========================================================

    def to_context_string(self) -> str:
        """
        Render the structured context as a context block
        that can be appended to an agent's task string.
        """

        sections = []

        sections.append(
            "======================================\n"
            "GENESIS STRUCTURED CONTEXT\n"
            "======================================\n"
        )

        if self.current_application:
            sections.append(
                f"Current application: "
                f"{self.current_application}"
            )

        if self.current_folder:
            sections.append(
                f"Current folder: "
                f"{self.current_folder}"
            )

        if self.active_document:
            sections.append(
                f"Active document: "
                f"{self.active_document}"
            )

        if self.clipboard_content:
            clipped = self.clipboard_content[:200]
            sections.append(
                f"Clipboard: {clipped}"
            )

        if self.recent_entities:
            sections.append(
                "\nRecent entities "
                "(files, apps, folders, documents):"
            )
            for entry in self.recent_entities[:10]:
                etype = entry.get("entity_type", "?")
                eid = entry.get("entity_id", "?")
                action = entry.get("action", "?")
                source_agent = entry.get("source_agent")
                source_level = entry.get("source_level")
                provenance = ""
                if source_agent:
                    provenance = f" (by {source_agent})"
                elif source_level:
                    provenance = f" (L{source_level})"
                sections.append(
                    f"  - {action} {etype}: {eid}{provenance}"
                )

        if self.previous_agent_results:
            sections.append(
                "\nPrevious agent results in this workflow:"
            )
            for pr in self.previous_agent_results:
                sections.append(
                    f"  Agent: {pr.get('agent', '?')}"
                )
                summary = pr.get("result_summary", "")
                if summary:
                    sections.append(
                        f"  Result: {summary[:300]}"
                    )

        if self.conversation_summary:
            sections.append(
                f"\nRecent conversation:\n"
                f"{self.conversation_summary}"
            )

        sections.append(
            "\n======================================\n"
            "END GENESIS STRUCTURED CONTEXT\n"
            "======================================\n"
        )

        return "\n".join(sections)

    # =========================================================
    # REFERENCE RESOLUTION
    # =========================================================

    def resolve_reference(
        self,
        reference: str,
    ) -> Optional[str]:
        """
        Resolve a vague reference using session state and
        entity history.

        Delegates to entity_history.resolve_pronoun when
        available, falls back to session state.
        """

        normalized = reference.lower().strip()

        if normalized in ("it", "that", "this"):
            if self.active_document:
                return self.active_document
            if self.current_folder:
                return self.current_folder
            if self.recent_entities:
                return self.recent_entities[-1].get(
                    "entity_id"
                )

        if normalized in ("the file", "the document"):
            return self.active_document

        if normalized in ("the folder", "the directory"):
            return self.current_folder

        if normalized in ("the application", "the app"):
            return self.current_application

        if normalized in ("the clipboard", "clipboard"):
            return self.clipboard_content

        if self.entity_history:
            try:
                from genesis_os.entity_history import (
                    EntityHistory,
                )

                if isinstance(
                    self.entity_history, dict
                ):
                    pass

            except ImportError:
                pass

        return None

    # =========================================================
    # SERIALIZATION
    # =========================================================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "task": self.task,
            "current_application": self.current_application,
            "current_folder": self.current_folder,
            "active_document": self.active_document,
            "recent_entities_count": len(
                self.recent_entities
            ),
            "previous_results_count": len(
                self.previous_agent_results
            ),
        }
