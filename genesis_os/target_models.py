"""
Genesis OS — Level 3.8.4 Target Models.

Target discovery and resolution models.

These models intentionally separate:

    target description
        ↓
    candidate
        ↓
    resolved target

A natural-language target is never treated as a filesystem
path or application identifier until the appropriate resolver
has explicitly resolved it.

Level 3.8.5 additions:
- ConversationContext for resolving pronouns / contextual references
  ("that file", "same folder", "open it").
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


TARGET_TYPES = frozenset({
    "file",
    "folder",
    "application",
    "url",
    "unknown",
})


@dataclass(frozen=True)
class TargetQuery:
    """
    Normalized description of the object a workflow step needs.
    """

    text: str

    target_type: str = "unknown"

    name: Optional[str] = None

    extension: Optional[str] = None

    application: Optional[str] = None

    location_hint: Optional[str] = None

    recency_preference: Optional[str] = None

    exact: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self):
        if not isinstance(self.text, str):
            raise TypeError(
                "TargetQuery.text must be a string."
            )

        if not self.text.strip():
            raise ValueError(
                "TargetQuery.text cannot be empty."
            )

        if self.target_type not in TARGET_TYPES:
            raise ValueError(
                f"Unsupported target type: "
                f"{self.target_type}"
            )


@dataclass(frozen=True)
class TargetCandidate:
    """
    A possible real-world target discovered by Genesis.
    """

    target_id: str

    target_type: str

    display_name: str

    value: str

    confidence: float

    source: str

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "Candidate confidence must be "
                "between 0 and 1."
            )

        if self.target_type not in TARGET_TYPES:
            raise ValueError(
                f"Unsupported target type: "
                f"{self.target_type}"
            )


@dataclass(frozen=True)
class ResolvedTarget:
    """
    A target that has passed deterministic resolution.
    """

    query: TargetQuery

    candidate: TargetCandidate

    confidence: float

    resolution_method: str

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def value(self) -> str:
        return self.candidate.value

    @property
    def target_type(self) -> str:
        return self.candidate.target_type

    @property
    def display_name(self) -> str:
        return self.candidate.display_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": {
                "text": self.query.text,
                "target_type": (
                    self.query.target_type
                ),
                "name": self.query.name,
                "extension": (
                    self.query.extension
                ),
                "application": (
                    self.query.application
                ),
                "location_hint": (
                    self.query.location_hint
                ),
                "recency_preference": (
                    self.query.recency_preference
                ),
                "exact": self.query.exact,
            },
            "candidate": {
                "target_id": (
                    self.candidate.target_id
                ),
                "target_type": (
                    self.candidate.target_type
                ),
                "display_name": (
                    self.candidate.display_name
                ),
                "value": self.candidate.value,
                "confidence": (
                    self.candidate.confidence
                ),
                "source": self.candidate.source,
                "metadata": dict(
                    self.candidate.metadata
                ),
            },
            "confidence": self.confidence,
            "resolution_method": (
                self.resolution_method
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class TargetResolutionResult:
    """
    Complete result of dynamic target resolution.
    """

    query: TargetQuery

    candidates: tuple[
        TargetCandidate,
        ...
    ]

    resolved: Optional[ResolvedTarget]

    requires_clarification: bool

    clarification_reason: Optional[str]

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def successful(self) -> bool:
        return (
            self.resolved is not None
            and not self.requires_clarification
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query.text,
            "target_type": (
                self.query.target_type
            ),
            "candidate_count": len(
                self.candidates
            ),
            "candidates": [
                {
                    "target_id": (
                        candidate.target_id
                    ),
                    "display_name": (
                        candidate.display_name
                    ),
                    "value": candidate.value,
                    "confidence": (
                        candidate.confidence
                    ),
                    "source": candidate.source,
                }
                for candidate in self.candidates
            ],
            "resolved": (
                self.resolved.to_dict()
                if self.resolved
                else None
            ),
            "requires_clarification": (
                self.requires_clarification
            ),
            "clarification_reason": (
                self.clarification_reason
            ),
            "metadata": dict(
                self.metadata
            ),
            "successful": self.successful,
        }


# =========================================================
# CONVERSATION CONTEXT — Pronoun / reference resolution
# =========================================================


@dataclass
class _Mention:
    """Internal record of a recently mentioned filesystem object."""
    path: str
    display_name: str
    mention_type: str  # "file" or "folder"
    timestamp: float = field(default_factory=time.time)


class ConversationContext:
    """Tracks recently mentioned files and folders for pronoun resolution.

    When a user says "that file" or "same folder", this context resolves
    the pronoun to the most recently mentioned object of the matching type.

    Usage::

        ctx = ConversationContext()
        ctx.update("file", "/home/user/report.pdf", "report.pdf")
        ctx.update("folder", "/home/user/Downloads", "Downloads")

        # Later, in a new turn:
        ctx.resolve_pronoun("that file")  # -> "/home/user/report.pdf"
        ctx.resolve_pronoun("same folder")  # -> "/home/user/Downloads"
    """

    _MAX_HISTORY: int = 20

    def __init__(self) -> None:
        self._mentions: Deque[_Mention] = deque(maxlen=self._MAX_HISTORY)

    def update(
        self,
        mention_type: str,
        path: str,
        display_name: Optional[str] = None,
    ) -> None:
        """Record a newly mentioned filesystem object."""
        if mention_type not in ("file", "folder"):
            raise ValueError(
                f"mention_type must be 'file' or 'folder', got '{mention_type}'"
            )
        self._mentions.append(_Mention(
            path=path,
            display_name=display_name or path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            mention_type=mention_type,
        ))

    def resolve_pronoun(self, text: str) -> Optional[str]:
        """Resolve a pronoun/reference phrase to a previously mentioned path.

        Returns the resolved filesystem path, or None if the context
        cannot resolve the reference.

        Recognized patterns:
        - "that file" / "this file" / "open it" / "that one"
        - "that folder" / "this folder" / "same folder"
        - "same directory" / "that directory"
        """
        lower = text.lower().strip()

        # Determine what type the user is referring to
        ref_type: Optional[str] = None

        if _PRONOUN_FILE_RE.search(lower):
            ref_type = "file"
        elif _PRONOUN_FOLDER_RE.search(lower):
            ref_type = "folder"

        # Ambiguous pronouns: "it", "that", "this", "that one"
        if ref_type is None and _PRONOUN_AMBIGUOUS_RE.search(lower):
            # Default to most recent mention of any type
            if self._mentions:
                return self._mentions[-1].path
            return None

        if ref_type is None:
            return None

        # Find most recent mention of the requested type
        for mention in reversed(self._mentions):
            if mention.mention_type == ref_type:
                return mention.path

        return None

    def last_mentioned_file(self) -> Optional[str]:
        """Return the path of the most recently mentioned file, or None."""
        for m in reversed(self._mentions):
            if m.mention_type == "file":
                return m.path
        return None

    def last_mentioned_folder(self) -> Optional[str]:
        """Return the path of the most recently mentioned folder, or None."""
        for m in reversed(self._mentions):
            if m.mention_type == "folder":
                return m.path
        return None

    def clear(self) -> None:
        """Clear all mentions."""
        self._mentions.clear()

    @property
    def history(self) -> List[Dict[str, Any]]:
        """Return a read-only snapshot of the mention history."""
        return [
            {
                "path": m.path,
                "display_name": m.display_name,
                "type": m.mention_type,
                "timestamp": m.timestamp,
            }
            for m in self._mentions
        ]


# Compiled regex patterns for pronoun detection
import re as _re

_PRONOUN_FILE_RE = _re.compile(
    r"\b(?:that|this|the|my)\s+file\b"
    r"|\bfile\b(?:\s+over\s+there)?"
    r"\b|\bit\b(?!\s*(?:is|was|has|will|can|should|does|didn|won|couldn|wouldn|shouldn))"
    r"|\bthat\s+one\b|\bthis\s+one\b",
    _re.IGNORECASE,
)

_PRONOUN_FOLDER_RE = _re.compile(
    r"\b(?:that|this|the|same)\s+(?:folder|directory)\b"
    r"|\bsame\s+folder\b"
    r"|\bsame\s+directory\b",
    _re.IGNORECASE,
)

_PRONOUN_AMBIGUOUS_RE = _re.compile(
    r"^(?:open|read|write|copy|move|delete|rename|show|find|get)\s+it\b"
    r"|\bthat\s+one\b|\bthis\s+one\b"
    r"|\bwhat\s+about\s+it\b"
    r"^\bit\b$",
    _re.IGNORECASE,
)