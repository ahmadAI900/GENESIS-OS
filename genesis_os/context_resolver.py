"""
Genesis OS — Level 3 Context Resolver.

Resolves natural language references using structured context:

    this / that / it
    the file / the document
    the folder / the directory
    the browser / the web browser
    the application / the app
    the previous file / the last file
    the latest file / the newest file
    the result / the output
    the window

Uses:
    conversation context
    task context
    OS state
    application state
    memory
    recent entities
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .session_state import SessionState
from agents.workflow_decision import WorkflowDecisionEngine
from .workflow_models import WorkflowState


@dataclass(frozen=True)
class ResolvedReference:
    """Result of resolving a natural language reference."""
    reference: str
    resolved_value: Any
    confidence: float
    source: str  # "session", "task", "conversation", "memory", "os_state"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference,
            "resolved_value": self.resolved_value,
            "confidence": self.confidence,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class ResolutionFailure:
    """Failed reference resolution with explanation."""
    reference: str
    reason: str
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference,
            "reason": self.reason,
            "suggestions": self.suggestions,
        }


class ContextResolver:
    """
    Resolves natural language references to concrete values.
    
    Architecture:
    
        User says "open it"
                ↓
        ContextResolver.resolve("it", context)
                ↓
        Checks in order:
            1. Task context (current step result)
            2. Session state (active document, current folder, etc.)
            3. Conversation history (recent entities)
            4. OS state (running apps, browser)
        ↓
        Returns ResolvedReference or ResolutionFailure
    """

    VERSION = "3.0.0"

    # Reference patterns and their resolvers
    REFERENCE_PATTERNS = {
        # Pronouns - highest priority for task context
        "this": ("task_context", 0.95),
        "that": ("task_context", 0.90),
        "it": ("task_context", 0.85),

        # File references
        "the file": ("active_document", 0.95),
        "the document": ("active_document", 0.90),
        "that file": ("recent_files", 0.80),
        "this file": ("active_document", 0.90),

        # Folder references
        "the folder": ("current_folder", 0.95),
        "the directory": ("current_folder", 0.90),
        "that folder": ("recent_folders", 0.80),

        # Browser references
        "the browser": ("browser", 0.95),
        "the web browser": ("browser", 0.90),
        "that browser": ("browser", 0.80),

        # Application references
        "the application": ("current_application", 0.95),
        "the app": ("current_application", 0.90),
        "that app": ("current_application", 0.80),

        # Result references
        "the result": ("last_task_result", 0.90),
        "the output": ("last_task_result", 0.85),
        "the outcome": ("last_task_result", 0.80),

        # Sequential references
        "the previous file": ("previous_file", 0.85),
        "the last file": ("previous_file", 0.80),
        "the latest file": ("latest_file", 0.90),
        "the newest file": ("latest_file", 0.85),
        "the first file": ("first_recent_file", 0.85),
        "the second file": ("second_recent_file", 0.80),
        "the first result": ("first_result", 0.85),
        "the second result": ("second_result", 0.80),

        # Window/UI references
        "the window": ("current_window", 0.80),
        "that window": ("current_window", 0.75),
    }

    def __init__(
        self,
        session_state: Optional[SessionState] = None,
        decision_engine: Optional[WorkflowDecisionEngine] = None,
    ):
        self.session_state = session_state
        self.decision_engine = decision_engine
        self._conversation_entities: List[Dict[str, Any]] = []

    def record_conversation_entity(self, entity: Dict[str, Any]) -> None:
        """Record an entity mentioned in conversation for later reference."""
        self._conversation_entities.insert(0, entity)
        self._conversation_entities = self._conversation_entities[:50]

    def resolve(
        self,
        reference: str,
        workflow_state: Optional[WorkflowState] = None,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> ResolvedReference | ResolutionFailure:
        """
        Resolve a natural language reference to a concrete value.
        
        Returns ResolvedReference on success, ResolutionFailure on failure.
        """
        ref = reference.lower().strip()

        # Direct pattern match
        if ref in self.REFERENCE_PATTERNS:
            source_type, base_confidence = self.REFERENCE_PATTERNS[ref]
            return self._resolve_by_source(
                ref, source_type, base_confidence,
                workflow_state, conversation_context
            )

        # Try fuzzy matching for compound references
        return self._resolve_compound(ref, workflow_state, conversation_context)

    def _resolve_by_source(
        self,
        reference: str,
        source_type: str,
        base_confidence: float,
        workflow_state: Optional[WorkflowState],
        conversation_context: Optional[Dict[str, Any]],
    ) -> ResolvedReference | ResolutionFailure:

        # Task context (current step result, etc.)
        if source_type == "task_context":
            return self._resolve_task_context(reference, workflow_state, conversation_context, base_confidence)

        # Session state sources
        if source_type == "active_document":
            return self._resolve_active_document(reference, base_confidence)
        if source_type == "current_folder":
            return self._resolve_current_folder(reference, base_confidence)
        if source_type == "recent_files":
            return self._resolve_recent_files(reference, 0, base_confidence)
        if source_type == "recent_folders":
            return self._resolve_recent_folders(reference, 0, base_confidence)
        if source_type == "browser":
            return self._resolve_browser(reference, base_confidence)
        if source_type == "current_application":
            return self._resolve_current_application(reference, base_confidence)
        if source_type == "last_task_result":
            return self._resolve_last_task_result(reference, workflow_state, base_confidence)
        if source_type == "previous_file":
            return self._resolve_recent_files(reference, 1, base_confidence)
        if source_type == "latest_file":
            return self._resolve_recent_files(reference, 0, base_confidence)
        if source_type == "first_recent_file":
            return self._resolve_recent_files(reference, 0, base_confidence)
        if source_type == "second_recent_file":
            return self._resolve_recent_files(reference, 1, base_confidence)
        if source_type == "first_result":
            return self._resolve_result_by_index(reference, 0, workflow_state, base_confidence)
        if source_type == "second_result":
            return self._resolve_result_by_index(reference, 1, workflow_state, base_confidence)
        if source_type == "current_window":
            return self._resolve_current_window(reference, base_confidence)

        return ResolutionFailure(
            reference=reference,
            reason=f"Unknown source type: {source_type}",
            suggestions=["Try a more specific reference"],
        )

    def _resolve_task_context(
        self,
        reference: str,
        workflow_state: Optional[WorkflowState],
        conversation_context: Optional[Dict[str, Any]],
        base_confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        """Resolve from task/workflow context."""
        # Check workflow state for current step result
        if workflow_state and workflow_state.current_step:
            step_key = f"step:{workflow_state.current_step}"
            if step_key in workflow_state.context:
                step_result = workflow_state.context[step_key]
                return ResolvedReference(
                    reference=reference,
                    resolved_value=step_result,
                    confidence=base_confidence,
                    source="task_context",
                    metadata={"step_id": workflow_state.current_step},
                )

        # Check conversation context for last result
        if conversation_context and "last_result" in conversation_context:
            return ResolvedReference(
                reference=reference,
                resolved_value=conversation_context["last_result"],
                confidence=base_confidence * 0.9,
                source="conversation",
                metadata={"source": "conversation_context"},
            )

        # Fall back to session state
        if self.session_state:
            return self._resolve_active_document(reference, base_confidence * 0.8)

        return ResolutionFailure(
            reference=reference,
            reason="No task context available",
            suggestions=["Execute a task first", "Be more specific about what 'it' refers to"],
        )

    def _resolve_active_document(
        self,
        reference: str,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            doc = self.session_state.get_active_document()
            if doc:
                return ResolvedReference(
                    reference=reference,
                    resolved_value=doc,
                    confidence=confidence,
                    source="session",
                    metadata={"type": "active_document"},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No active document in session",
            suggestions=["Open or create a document first"],
        )

    def _resolve_current_folder(
        self,
        reference: str,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            folder = self.session_state.get_current_folder()
            if folder:
                return ResolvedReference(
                    reference=reference,
                    resolved_value=folder,
                    confidence=confidence,
                    source="session",
                    metadata={"type": "current_folder"},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No current folder in session",
            suggestions=["Navigate to a folder first"],
        )

    def _resolve_recent_files(
        self,
        reference: str,
        index: int,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            files = self.session_state.get_recent_files(limit=20)
            if files and index < len(files):
                return ResolvedReference(
                    reference=reference,
                    resolved_value=files[index],
                    confidence=confidence * (0.9 ** index),
                    source="session",
                    metadata={"type": "recent_file", "index": index},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No recent files available",
            suggestions=["Work with some files first"],
        )

    def _resolve_recent_folders(
        self,
        reference: str,
        index: int,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            folders = self.session_state._recent_folders
            if folders and index < len(folders):
                return ResolvedReference(
                    reference=reference,
                    resolved_value=folders[index],
                    confidence=confidence * (0.9 ** index),
                    source="session",
                    metadata={"type": "recent_folder", "index": index},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No recent folders available",
            suggestions=["Navigate to some folders first"],
        )

    def _resolve_browser(
        self,
        reference: str,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            browser = self.session_state.get_browser()
            if browser:
                return ResolvedReference(
                    reference=reference,
                    resolved_value={
                        "browser_name": browser.browser_name,
                        "current_url": browser.current_url,
                        "current_tab_title": browser.current_tab_title,
                    },
                    confidence=confidence,
                    source="session",
                    metadata={"type": "browser_state"},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No browser state in session",
            suggestions=["Open a browser first"],
        )

    def _resolve_current_application(
        self,
        reference: str,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            app = self.session_state.get_current_application()
            if app:
                return ResolvedReference(
                    reference=reference,
                    resolved_value={
                        "name": app.name,
                        "process_id": app.process_id,
                        "window_title": app.window_title,
                    },
                    confidence=confidence,
                    source="session",
                    metadata={"type": "current_application"},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No current application in session",
            suggestions=["Open an application first"],
        )

    def _resolve_last_task_result(
        self,
        reference: str,
        workflow_state: Optional[WorkflowState],
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if workflow_state and workflow_state.context:
            # Look for last completed step result
            for step_id in reversed(workflow_state.completed_steps):
                step_key = f"step:{step_id}"
                if step_key in workflow_state.context:
                    return ResolvedReference(
                        reference=reference,
                        resolved_value=workflow_state.context[step_key],
                        confidence=confidence,
                        source="task",
                        metadata={"step_id": step_id},
                    )
        return ResolutionFailure(
            reference=reference,
            reason="No previous task result",
            suggestions=["Complete a task first"],
        )

    def _resolve_result_by_index(
        self,
        reference: str,
        index: int,
        workflow_state: Optional[WorkflowState],
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if workflow_state and workflow_state.completed_steps:
            if index < len(workflow_state.completed_steps):
                step_id = workflow_state.completed_steps[index]
                step_key = f"step:{step_id}"
                if step_key in workflow_state.context:
                    return ResolvedReference(
                        reference=reference,
                        resolved_value=workflow_state.context[step_key],
                        confidence=confidence,
                        source="task",
                        metadata={"step_id": step_id, "index": index},
                    )
        return ResolutionFailure(
            reference=reference,
            reason=f"No result at index {index}",
            suggestions=["Complete more task steps first"],
        )

    def _resolve_current_window(
        self,
        reference: str,
        confidence: float,
    ) -> ResolvedReference | ResolutionFailure:
        if self.session_state:
            app = self.session_state.get_current_application()
            if app and app.window_title:
                return ResolvedReference(
                    reference=reference,
                    resolved_value=app.window_title,
                    confidence=confidence,
                    source="session",
                    metadata={"type": "window_title", "application": app.name},
                )
        return ResolutionFailure(
            reference=reference,
            reason="No current window tracked",
            suggestions=["Focus an application window first"],
        )

    def _resolve_compound(
        self,
        reference: str,
        workflow_state: Optional[WorkflowState],
        conversation_context: Optional[Dict[str, Any]],
    ) -> ResolvedReference | ResolutionFailure:
        """Try to resolve compound references like 'the file we just opened'."""
        # Check conversation entities
        for entity in self._conversation_entities:
            entity_type = entity.get("type", "")
            entity_value = entity.get("value", "")

            if "file" in reference and entity_type in ("file", "document"):
                return ResolvedReference(
                    reference=reference,
                    resolved_value=entity_value,
                    confidence=0.75,
                    source="conversation",
                    metadata=entity,
                )
            if "folder" in reference and entity_type in ("folder", "directory"):
                return ResolvedReference(
                    reference=reference,
                    resolved_value=entity_value,
                    confidence=0.75,
                    source="conversation",
                    metadata=entity,
                )
            if "app" in reference and entity_type in ("application", "app"):
                return ResolvedReference(
                    reference=reference,
                    resolved_value=entity_value,
                    confidence=0.75,
                    source="conversation",
                    metadata=entity,
                )

        return ResolutionFailure(
            reference=reference,
            reason=f"Could not resolve reference: {reference}",
            suggestions=[
                "Be more specific (e.g., 'the downloads folder' instead of 'it')",
                "Execute the target operation first to establish context",
            ],
        )


class ContextAwareWorkflowDecision:
    """
    Enhanced workflow decision that incorporates context resolution.
    
    Extends WorkflowDecisionEngine to resolve references before deciding.
    """

    def __init__(
        self,
        base_engine: WorkflowDecisionEngine,
        context_resolver: ContextResolver,
    ):
        self.base_engine = base_engine
        self.context_resolver = context_resolver

    def decide_with_context(
        self,
        text: str,
        workflow_state: Optional[WorkflowState] = None,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Decide workflow with context-aware reference resolution.
        
        First resolves any references in the text, then makes decision.
        """
        # Try to resolve common reference patterns in the text
        resolved_text = self._resolve_references_in_text(
            text, workflow_state, conversation_context
        )

        # Use base engine for decision
        decision = self.base_engine.decide(resolved_text)

        # Add resolution metadata
        if resolved_text != text:
            decision["resolved_references"] = True
            decision["original_text"] = text
            decision["resolved_text"] = resolved_text

        return decision

    def _resolve_references_in_text(
        self,
        text: str,
        workflow_state: Optional[WorkflowState],
        conversation_context: Optional[Dict[str, Any]],
    ) -> str:
        """Resolve references embedded in natural language text."""
        # Simple reference replacement for common patterns
        # In a full implementation, this would use NLP to identify reference spans
        
        replacements = {
            " open it": " open the file",
            " open that": " open the file",
            " close it": " close the application",
            " find it": " find the file",
            " search for it": " search for the file",
            " in it": " in the folder",
            " to it": " to the folder",
            " from it": " from the folder",
            " the browser": " the browser",
            " the app": " the application",
        }

        result = text.lower()
        for pattern, replacement in replacements.items():
            if pattern in result:
                # Check if we can actually resolve it
                ref = pattern.replace(" ", "").replace("open", "").replace("close", "").replace("find", "").replace("search for", "").replace("in", "").replace("to", "").replace("from", "").replace("the ", "")
                resolution = self.context_resolver.resolve(ref, workflow_state, conversation_context)
                if isinstance(resolution, ResolvedReference) and resolution.resolved_value:
                    result = result.replace(pattern, replacement)
                    # Store the resolved value for later use
                    if not hasattr(self, '_resolved_values'):
                        self._resolved_values = {}
                    self._resolved_values[pattern.strip()] = resolution.resolved_value

        return result