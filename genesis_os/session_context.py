"""
Genesis OS — Level 3.9
Session Context Binding.

Binds natural conversational continuations onto the previous
Level 3 operating-system context:

    User:  "Open Chrome."
    User:  "Now search YouTube for Python."

    User:  "Open my Downloads folder."
    User:  "Now find the IELTS file."

Discourse markers such as "now", "then", "next" are NOT OS
intent. They are conversational glue left over from the previous
turn. This binder strips them and re-evaluates the remaining
request through the EXISTING WorkflowDecisionEngine instead of
duplicating intent detection.

Design constraints:

    - No invented execution: if the remaining request cannot be
      resolved as a confident Level 3 operation, the binder
      declines and the normal routing pipeline handles the turn.
    - Anaphoric requests whose referent requires observing live
      application state (for example "open the first result")
      are explicitly NOT faked. They stay unbound until real
      browser/application observation exists.

Cross-level reference resolution:

    - When a Level 2 agent creates an entity (file, document,
      etc.), the entity is recorded in entity_history.
    - A subsequent Level 3 turn can reference that entity via
      "open it", "open the file", etc.
    - The binder resolves these references using entity_history
      before re-evaluating through WorkflowDecisionEngine.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


class SessionContextBinder:

    VERSION = "3.9.0"

    MINIMUM_CONFIDENCE = 0.90

    # Conversational glue that may prefix a follow-up request.
    _MARKER_RE = re.compile(
        r"^(?:now|then|next|after\s+that|afterwards|also|and)\b[\s,:-]+",
        re.IGNORECASE,
    )

    # Requests that reference live application/UI state which
    # Genesis cannot yet honestly observe. These are declined
    # rather than guessed.
    _UNBOUND_ANAPHORA_RE = re.compile(
        r"^(?:open|go\s+to|visit|show|read|click|select|load)?\s*"
        r"(?:the\s+)?"
        r"(?:first|second|third|top|best|next)\s+"
        r"(?:result|link|video|match|hit|item)s?\b",
        re.IGNORECASE,
    )

    # Pronouns and vague references that need entity resolution
    _REFERENCE_RE = re.compile(
        r"\b(it|that|this|them|those|the\s+file|the\s+document|"
        r"the\s+spreadsheet|the\s+folder|the\s+app(?:lication)?|"
        r"the\s+newest\s+\w+|the\s+original|the\s+final)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        decision_engine,
    ):
        if decision_engine is None or not hasattr(
            decision_engine, "decide"
        ):
            raise TypeError(
                "SessionContextBinder requires a "
                "WorkflowDecisionEngine-compatible object."
            )

        self.decision_engine = decision_engine

        self._application: Optional[str] = None

        self._intent: Optional[str] = None

        self._target: Optional[str] = None

        self._engine: Optional[str] = None

        self._entity_history = None

    # =========================================================
    # ENTITY HISTORY INTEGRATION
    # =========================================================

    def set_entity_history(self, entity_history):
        """
        Inject entity history for cross-level reference resolution.
        """

        self._entity_history = entity_history

    def _resolve_entity_reference(self, text: str) -> Optional[str]:
        """
        Attempt to resolve pronouns and vague references in the text
        using entity history.

        Returns the text with references resolved, or None if
        no resolution is possible.
        """

        if self._entity_history is None:
            return None

        match = self._REFERENCE_RE.search(text)
        if not match:
            return None

        reference = match.group(0).lower().strip()

        resolved = None

        try:
            from genesis_os.entity_history import EntityType

            type_hints = {
                "the file": EntityType.FILE,
                "the document": EntityType.DOCUMENT,
                "the spreadsheet": EntityType.SPREADSHEET,
                "the folder": EntityType.FOLDER,
                "the application": EntityType.APPLICATION,
                "the app": EntityType.APPLICATION,
            }

            entity_type_hint = type_hints.get(reference)

            resolved = self._entity_history.resolve_pronoun(
                reference,
                entity_type_hint=entity_type_hint,
            )

        except Exception:
            return None

        if not resolved:
            return None

        resolved_text = text[:match.start()] + resolved + text[match.end():]
        return resolved_text

    # =========================================================
    # CONTEXT RECORDING
    # =========================================================

    @property
    def has_context(self) -> bool:
        return any(
            value is not None
            for value in (
                self._application,
                self._intent,
                self._target,
                self._engine,
            )
        )

    def record_decision(
        self,
        decision: Dict[str, Any],
    ) -> None:
        """
        Record the durable parts of a successful Level 3 turn.

        Only strong decisions are recorded so weak guesses never
        become future context.
        """

        if not isinstance(decision, dict):
            return

        if decision.get("level") != 3:
            return

        if float(decision.get("confidence", 0.0)) < (
            self.MINIMUM_CONFIDENCE
        ):
            return

        application = decision.get("application")

        if application:
            self._application = str(application)

        intent = (
            decision.get("operation")
            or decision.get("intent")
        )

        if intent:
            self._intent = str(intent)

        target = decision.get("target")

        if target:
            self._target = str(target)

        parameters = decision.get("parameters") or {}

        engine = parameters.get("engine")

        if engine:
            self._engine = str(engine)

    def reset(self) -> None:

        self._application = None
        self._intent = None
        self._target = None
        self._engine = None

    # =========================================================
    # CONTINUATION REBINDING
    # =========================================================

    def try_rebind(
        self,
        text: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to interpret `text` as a continuation of the
        previous Level 3 turn.

        Returns a fresh workflow decision when the stripped
        request resolves confidently as a Level 3 operation,
        otherwise None.
        """

        if not isinstance(text, str):
            return None

        # -----------------------------------------------
        # STEP 1: Try entity reference resolution
        #
        # "Open it" -> "Open C:\Users\...\results.xlsx"
        # Then re-evaluate the resolved text.
        # -----------------------------------------------

        # `entity_resolved` records that the resolution actually rewrote
        # the text. It MUST be captured here, before `text` is reassigned:
        # afterwards `text is resolved_text`, so re-deriving the fact later
        # compares the value to itself and is always False. That is exactly
        # how the "resolved a bare pronoun, but stripping was a no-op"
        # branch below used to become unreachable (2026-10-15).
        entity_resolved = False
        resolved_text = self._resolve_entity_reference(text)
        if resolved_text is not None and resolved_text != text:
            print(
                "[Genesis Session] "
                f"Entity reference resolved: "
                f"'{text}' -> '{resolved_text}'"
            )
            entity_resolved = True
            text = resolved_text

        # -----------------------------------------------
        # STEP 2: Standard marker stripping + rebind
        # -----------------------------------------------

        if not self.has_context:
            return None

        stripped = self._strip_markers(text)

        if not stripped or stripped == text:
            # Nothing was stripped. That is only fatal if no entity
            # reference was resolved either. If one WAS, the resolved
            # text is already the whole request -- "open it" became
            # "open C:\report.xlsx" and there is no marker to remove --
            # so decide it rather than dropping a valid level-3 turn.
            if entity_resolved:
                stripped = self._strip_markers(resolved_text)
                if not stripped:
                    return None
            else:
                return None

        if self._UNBOUND_ANAPHORA_RE.match(stripped):
            # Live-result selection is not yet observable;
            # never fake it.
            return None

        decision = self.decision_engine.decide(stripped)

        if not isinstance(decision, dict):
            return None

        if decision.get("level") != 3:
            return None

        if float(
            decision.get("confidence", 0.0)
        ) < self.MINIMUM_CONFIDENCE:
            return None

        return decision

    # =========================================================
    # INTERNALS
    # =========================================================

    @staticmethod
    def _strip_markers(text: Any) -> str:

        if not isinstance(text, str):
            return ""

        current = " ".join(text.split())

        for _ in range(4):
            match = SessionContextBinder._MARKER_RE.match(
                current
            )

            if not match:
                break

            current = current[match.end():].strip()

        return current
