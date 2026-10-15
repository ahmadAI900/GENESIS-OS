"""
Genesis OS — Level 3 Context Resolution Pipeline.

Unified context resolution integrating:
    ContextResolver  — natural-language reference resolution
    SessionContextBinder — multi-turn continuation binding
    SessionState — OS session state tracking
    MultiTurnTracker — accumulated task context across turns

Pipeline flow:

    User input text
        → ContextPipeline.resolve_input()
        → _resolve_references()     — replace "it", "that file", etc.
        → _check_continuation()     — detect "now ...", "then ..." glue
        → _enrich_with_context()    — inject session metadata
        → _extract_entities()       — pull mentioned files/folders/apps
        → ResolvedInput (frozen, safe to pass downstream)

Design constraints:

    - Non-blocking: errors in any sub-resolver are caught and
      reported as zero-confidence rather than crashing the system.
    - Backward-compatible: existing code that calls
      ContextResolver.resolve() or SessionContextBinder.try_rebind()
      continues to work unchanged.
    - Supports mixed Level 2+3 workflows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .context_resolver import ContextResolver, ResolvedReference, ResolutionFailure
from .session_context import SessionContextBinder
from .session_state import SessionState
from .workflow_models import WorkflowState


# ---------------------------------------------------------------------------
# ResolvedInput — immutable output of the pipeline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedInput:
    """Unified result of context resolution for one user turn."""

    original_text: str
    resolved_text: str
    is_continuation: bool
    continuation_context: Optional[dict]
    resolved_references: Dict[str, Any]
    entities: List[Dict[str, Any]]
    session_context: Dict[str, Any]
    confidence: float


# ---------------------------------------------------------------------------
# MultiTurnTracker — accumulates context across turns
# ---------------------------------------------------------------------------

class MultiTurnTracker:
    """Tracks multi-turn task context for Level 3 workflows.

    Records every completed turn (text + decision + result) and exposes
    helpers that surface recently-accessed files, folders, and applications
    so that the context resolver and session binder can leverage them.
    """

    def __init__(self) -> None:
        self._turns: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_turn(
        self,
        text: str,
        decision: Dict[str, Any],
        result: Any = None,
    ) -> None:
        """Record a completed turn.

        Parameters
        ----------
        text : str
            The original user text for this turn.
        decision : dict
            The workflow decision returned by the decision engine.
        result : Any, optional
            The execution result (may be a string, dict, or None).
        """
        entities = self._extract_entities_from_decision(decision)
        turn: Dict[str, Any] = {
            "text": text,
            "decision": dict(decision),
            "result": result,
            "entities": entities,
        }
        self._turns.append(turn)
        # Keep a bounded history
        if len(self._turns) > 100:
            self._turns = self._turns[-100:]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_current_task_context(self) -> Dict[str, Any]:
        """Return accumulated context from all recorded turns.

        Returns a dict with keys:
            turns          — number of recorded turns
            recent_texts   — last 5 user texts
            recent_entities — flattened recent entities
        """
        recent_texts = [t["text"] for t in self._turns[-5:]]
        recent_entities: List[Dict[str, Any]] = []
        for turn in self._turns[-5:]:
            recent_entities.extend(turn.get("entities", []))
        return {
            "turns": len(self._turns),
            "recent_texts": recent_texts,
            "recent_entities": recent_entities,
        }

    def get_recent_entities(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return the last *n* entities mentioned across turns."""
        entities: List[Dict[str, Any]] = []
        for turn in reversed(self._turns):
            entities.extend(turn.get("entities", []))
            if len(entities) >= n:
                break
        return entities[:n]

    def get_recent_files(self) -> List[str]:
        """Return recently accessed file paths (most recent first)."""
        files: List[str] = []
        seen: set[str] = set()
        for turn in reversed(self._turns):
            for entity in turn.get("entities", []):
                if entity.get("type") in ("file", "document", "spreadsheet"):
                    value = entity.get("value", "")
                    if value and value not in seen:
                        seen.add(value)
                        files.append(value)
        return files

    def get_recent_folders(self) -> List[str]:
        """Return recently accessed folder paths (most recent first)."""
        folders: List[str] = []
        seen: set[str] = set()
        for turn in reversed(self._turns):
            for entity in turn.get("entities", []):
                if entity.get("type") in ("folder", "directory"):
                    value = entity.get("value", "")
                    if value and value not in seen:
                        seen.add(value)
                        folders.append(value)
        return folders

    def get_recent_applications(self) -> List[str]:
        """Return recently used application names (most recent first)."""
        apps: List[str] = []
        seen: set[str] = set()
        for turn in reversed(self._turns):
            for entity in turn.get("entities", []):
                if entity.get("type") in ("application", "app"):
                    value = entity.get("value", "")
                    if value and value not in seen:
                        seen.add(value)
                        apps.append(value)
        return apps

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all accumulated context."""
        self._turns.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tracker state."""
        return {
            "turns": list(self._turns),
            "turn_count": len(self._turns),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_entities_from_decision(
        decision: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Pull file/folder/app entities out of a workflow decision."""
        entities: List[Dict[str, Any]] = []
        target = decision.get("target")
        application = decision.get("application")
        parameters = decision.get("parameters") or {}

        if target:
            entity_type = MultiTurnTracker._infer_type(target, decision)
            entities.append({"type": entity_type, "value": target, "role": "target"})

        if application and application != target:
            entities.append({"type": "application", "value": application, "role": "application"})

        dest = parameters.get("destination")
        if dest:
            entities.append({"type": "folder", "value": dest, "role": "destination"})

        source = parameters.get("source")
        if source:
            entities.append({"type": "file", "value": source, "role": "source"})

        return entities

    @staticmethod
    def _infer_type(target: str, decision: Dict[str, Any]) -> str:
        operation = decision.get("operation") or decision.get("intent", "")
        if operation.startswith("application."):
            return "application"
        if operation.startswith("folder."):
            return "folder"
        if operation.startswith("file."):
            return "file"
        if operation.startswith("browser."):
            return "url"
        if operation.startswith("spreadsheet."):
            return "spreadsheet"
        if operation.startswith("document."):
            return "document"
        if target.startswith("http"):
            return "url"
        if any(target.endswith(e) for e in (".xlsx", ".xls", ".csv")):
            return "spreadsheet"
        if any(target.endswith(e) for e in (".docx", ".doc", ".pdf", ".txt")):
            return "document"
        return "unknown"


# ---------------------------------------------------------------------------
# ContextPipeline — unified context resolution
# ---------------------------------------------------------------------------

# Pronouns / demonstratives that signal a reference to prior context
_REFERENCE_RE = re.compile(
    r"\b(?:it|this|that|these|those|"
    r"the\s+(?:file|document|folder|directory|browser|web\s+browser|"
    r"application|app|result|output|window|spreadsheet|"
    r"previous\s+file|last\s+file|latest\s+file|newest\s+file|"
    r"first\s+file|second\s+file|first\s+result|second\s+result))\b",
    re.IGNORECASE,
)

# Conversational glue markers
_MARKER_RE = re.compile(
    r"^(?:now|then|next|after\s+that|afterwards|also|and)\b[\s,:-]+",
    re.IGNORECASE,
)


class ContextPipeline:
    """Unified context resolution pipeline.

    Combines reference resolution, session-context continuation,
    and multi-turn tracking into a single entry-point that
    downstream consumers can call once per user turn.
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        session_state: Optional[SessionState] = None,
        decision_engine: Any = None,
        context_resolver: Optional[ContextResolver] = None,
        session_binder: Optional[SessionContextBinder] = None,
    ) -> None:
        self.session_state = session_state
        self.decision_engine = decision_engine

        # Create or reuse sub-resolvers
        self.context_resolver = context_resolver or (
            ContextResolver(
                session_state=session_state,
                decision_engine=decision_engine,
            )
            if session_state or decision_engine
            else ContextResolver()
        )

        self.session_binder = session_binder or (
            SessionContextBinder(decision_engine)
            if decision_engine
            else None
        )

        self.multi_turn_tracker = MultiTurnTracker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_input(
        self,
        text: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        workflow_state: Optional[WorkflowState] = None,
    ) -> ResolvedInput:
        """Resolve a single user input into a ResolvedInput.

        This is the main entry-point.  Every sub-step is wrapped in a
        try/except so that a failure in one layer never crashes the caller.
        """

        if not text or not text.strip():
            return ResolvedInput(
                original_text=text or "",
                resolved_text=text or "",
                is_continuation=False,
                continuation_context=None,
                resolved_references={},
                entities=[],
                session_context={},
                confidence=0.0,
            )

        original_text = text
        resolved_references: Dict[str, Any] = {}
        continuation_context: Optional[dict] = None
        is_continuation = False
        confidence = 1.0

        # Step 1 — Detect continuation before reference resolution
        try:
            continuation_info = self._check_continuation(text, self.session_binder)
            if continuation_info is not None:
                is_continuation = True
                continuation_context = continuation_info
                # Use the rebound decision's text if available
                if continuation_info.get("resolved_text"):
                    text = continuation_info["resolved_text"]
        except Exception as exc:
            # Non-blocking: continuation failure is not fatal
            _debug(f"[ContextPipeline] continuation check failed: {exc}")

        # Step 2 — Resolve natural-language references
        try:
            text, refs, ref_confidence = self._resolve_references(
                text, self.session_state, workflow_state,
            )
            resolved_references.update(refs)
            confidence *= ref_confidence
        except Exception as exc:
            _debug(f"[ContextPipeline] reference resolution failed: {exc}")

        # Step 3 — Enrich with session context metadata
        try:
            text = self._enrich_with_context(text, self.session_state)
        except Exception as exc:
            _debug(f"[ContextPipeline] context enrichment failed: {exc}")

        # Step 4 — Extract entities
        try:
            entities = self._extract_entities(text)
        except Exception as exc:
            _debug(f"[ContextPipeline] entity extraction failed: {exc}")
            entities = []

        # Step 5 — Build session_context summary
        session_context = self._build_session_summary(self.session_state)

        return ResolvedInput(
            original_text=original_text,
            resolved_text=text,
            is_continuation=is_continuation,
            continuation_context=continuation_context,
            resolved_references=resolved_references,
            entities=entities,
            session_context=session_context,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Recording (for multi-turn tracking)
    # ------------------------------------------------------------------

    def record_turn(
        self,
        text: str,
        decision: Dict[str, Any],
        result: Any = None,
    ) -> None:
        """Record a completed turn for multi-turn tracking.

        Should be called after the system has executed the turn.
        """
        self.multi_turn_tracker.record_turn(text, decision, result)

        # Also feed the context resolver with any entities
        try:
            entities = self.multi_turn_tracker._extract_entities_from_decision(decision)
            for entity in entities:
                self.context_resolver.record_conversation_entity(entity)
        except Exception:
            pass

        # Feed session binder
        if self.session_binder is not None:
            try:
                self.session_binder.record_decision(decision)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal — reference resolution
    # ------------------------------------------------------------------

    def _resolve_references(
        self,
        text: str,
        session_state: Optional[SessionState],
        workflow_state: Optional[WorkflowState],
    ) -> tuple[str, Dict[str, Any], float]:
        """Replace natural-language references with resolved values.

        Returns (resolved_text, references_map, confidence_factor).
        """
        references: Dict[str, Any] = {}
        confidence_factor = 1.0
        result = text

        for match in _REFERENCE_RE.finditer(text):
            ref_text = match.group(0).strip()
            ref_lower = ref_text.lower()

            resolution = self.context_resolver.resolve(
                ref_lower, workflow_state=workflow_state,
            )

            if isinstance(resolution, ResolvedReference):
                resolved_value = resolution.resolved_value
                references[ref_text] = {
                    "resolved_value": resolved_value,
                    "confidence": resolution.confidence,
                    "source": resolution.source,
                }
                # Replace only if the resolved value is a simple string
                if isinstance(resolved_value, str):
                    result = result.replace(ref_text, resolved_value, 1)
                confidence_factor *= resolution.confidence
            elif isinstance(resolution, ResolutionFailure):
                # Could not resolve — leave the reference in place
                # but lower confidence slightly
                confidence_factor *= 0.9

        return result, references, confidence_factor

    # ------------------------------------------------------------------
    # Internal — continuation detection
    # ------------------------------------------------------------------

    def _check_continuation(
        self,
        text: str,
        session_binder: Optional[SessionContextBinder],
    ) -> Optional[dict]:
        """Check if this input is a continuation of a previous turn.

        Uses the SessionContextBinder to strip discourse markers and
        rebind against the last Level 3 decision.
        """
        if session_binder is None or not session_binder.has_context:
            return None

        rebinding = session_binder.try_rebind(text)
        if rebinding is None:
            return None

        # Build a lightweight context dict from the rebound decision
        return {
            "type": "continuation",
            "decision": rebinding,
            "resolved_text": (
                rebinding.get("target")
                or rebinding.get("application")
                or text
            ),
            "application": rebinding.get("application"),
            "operation": rebinding.get("operation") or rebinding.get("intent"),
            "target": rebinding.get("target"),
        }

    # ------------------------------------------------------------------
    # Internal — context enrichment
    # ------------------------------------------------------------------

    def _enrich_with_context(
        self,
        text: str,
        session_state: Optional[SessionState],
    ) -> str:
        """Append contextual metadata to the text so downstream
        consumers can leverage session state without re-querying it.

        Only adds information when there is meaningful session state;
        empty sessions produce no enrichment.
        """
        if session_state is None:
            return text

        hints: List[str] = []

        try:
            active_doc = session_state.get_active_document()
            if active_doc:
                hints.append(f"[active_document={active_doc}]")
        except Exception:
            pass

        try:
            current_folder = session_state.get_current_folder()
            if current_folder:
                hints.append(f"[current_folder={current_folder}]")
        except Exception:
            pass

        try:
            app = session_state.get_current_application()
            if app and app.name:
                hints.append(f"[current_application={app.name}]")
        except Exception:
            pass

        try:
            recent_files = session_state.get_recent_files(limit=3)
            if recent_files:
                hints.append(f"[recent_files={','.join(recent_files)}]")
        except Exception:
            pass

        if hints:
            return f"{text}  {' '.join(hints)}"

        return text

    # ------------------------------------------------------------------
    # Internal — entity extraction
    # ------------------------------------------------------------------

    def _extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract mentioned entities from the (possibly enriched) text.

        This is a lightweight heuristic extraction.  The real entity
        resolution happens in ContextResolver and ObjectiveUnderstanding.
        """
        entities: List[Dict[str, Any]] = []
        lower = text.lower()

        # File-like paths (simple heuristic)
        import os
        # Windows-style paths
        for token in text.split():
            token_clean = token.strip('",.')
            if (
                "\\" in token_clean
                or "/" in token_clean
                or token_clean.endswith((".txt", ".docx", ".pdf", ".xlsx",
                                        ".csv", ".py", ".json", ".png",
                                        ".jpg", ".exe", ".zip"))
            ):
                entities.append({
                    "type": "file" if "." in os.path.basename(token_clean) else "folder",
                    "value": token_clean,
                    "role": "mentioned",
                })

        # Application names (common)
        app_keywords = [
            "chrome", "firefox", "edge", "excel", "word", "powerpoint",
            "notepad", "vscode", "visual studio", "file explorer",
            "explorer", "calculator", "paint", "photoshop", "spotify",
            "zoom", "teams", "slack", "terminal", "command prompt",
        ]
        for app in app_keywords:
            if app in lower:
                entities.append({
                    "type": "application",
                    "value": app,
                    "role": "mentioned",
                })

        # Folder keywords
        folder_keywords = [
            "downloads", "documents", "desktop", "pictures", "music",
            "videos", "documents folder", "downloads folder",
        ]
        for folder in folder_keywords:
            if folder in lower:
                entities.append({
                    "type": "folder",
                    "value": folder,
                    "role": "mentioned",
                })

        return entities

    # ------------------------------------------------------------------
    # Internal — session summary
    # ------------------------------------------------------------------

    @staticmethod
    def _build_session_summary(
        session_state: Optional[SessionState],
    ) -> Dict[str, Any]:
        """Build a lightweight summary of the current session state."""
        if session_state is None:
            return {}

        summary: Dict[str, Any] = {}

        try:
            doc = session_state.get_active_document()
            if doc:
                summary["active_document"] = doc
        except Exception:
            pass

        try:
            folder = session_state.get_current_folder()
            if folder:
                summary["current_folder"] = folder
        except Exception:
            pass

        try:
            app = session_state.get_current_application()
            if app:
                summary["current_application"] = app.name
        except Exception:
            pass

        try:
            browser = session_state.get_browser()
            if browser:
                summary["browser"] = {
                    "name": browser.browser_name,
                    "url": browser.current_url,
                }
        except Exception:
            pass

        try:
            files = session_state.get_recent_files(limit=5)
            if files:
                summary["recent_files"] = files
        except Exception:
            pass

        return summary


# ---------------------------------------------------------------------------
# Module-level debug helper (avoids import of logging in hot path)
# ---------------------------------------------------------------------------

def _debug(msg: str) -> None:
    """Print a debug message.  Swallowed silently if running in
    environments that suppress stdout."""
    try:
        print(msg)
    except Exception:
        pass
