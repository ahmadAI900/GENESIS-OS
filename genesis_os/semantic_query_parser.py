"""
Genesis OS — Level 3.8.4+ Semantic Query Parser.

Extracts structured preferences from natural-language target descriptions
before file/folder discovery.

Converts:
    "my latest PDF"
        -> recency=newest, extension=.pdf

    "the newest spreadsheet in Documents"
        -> recency=newest, type=spreadsheet, location=Documents

    "the report I edited yesterday"
        -> recency=yesterday, name=report

    "the file we worked on"
        -> recency=session, name=file

    "the original"
        -> concept=original

    "the copy"
        -> concept=copy

    "save beside the original"
        -> relative_to=original

This layer intentionally does NOT access the filesystem.
It only extracts structured intent from text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# =========================================================
# KNOWN ALIASES
# =========================================================

_KNOWN_EXTENSIONS: Dict[str, str] = {
    "pdf": ".pdf",
    "pdfs": ".pdf",
    "excel": ".xlsx",
    "spreadsheet": ".xlsx",
    "spreadsheets": ".xlsx",
    "csv": ".csv",
    "word": ".docx",
    "document": ".docx",
    "documents": ".docx",
    "docx": ".docx",
    "doc": ".doc",
    "text": ".txt",
    "txt": ".txt",
    "powerpoint": ".pptx",
    "presentation": ".pptx",
    "pptx": ".pptx",
    "image": ".png",
    "images": ".png",
    "photo": ".jpg",
    "photos": ".jpg",
    "picture": ".jpg",
    "pictures": ".jpg",
    "jpg": ".jpg",
    "jpeg": ".jpeg",
    "png": ".png",
    "mp3": ".mp3",
    "music": ".mp3",
    "song": ".mp3",
    "songs": ".mp3",
    "mp4": ".mp4",
    "video": ".mp4",
    "videos": ".mp4",
    "zip": ".zip",
    "archive": ".zip",
    "python": ".py",
    "script": ".py",
    "html": ".html",
    "json": ".json",
    "xml": ".xml",
}

_LOCATION_ALIASES: Dict[str, str] = {
    "downloads": "downloads",
    "download": "downloads",
    "documents": "documents",
    "document": "documents",
    "desktop": "desktop",
    "pictures": "pictures",
    "photos": "pictures",
    "music": "music",
    "videos": "videos",
    "video": "videos",
    "workspace": "workspace",
    "current": "workspace",
}


# =========================================================
# SEMANTIC PARSING RESULT
# =========================================================


@dataclass(frozen=True)
class ParsedSemanticQuery:
    """Structured extraction from a natural-language target description."""

    original_text: str
    name_terms: Tuple[str, ...] = ()
    extension: Optional[str] = None
    recency: Optional[str] = None
    location: Optional[str] = None
    relative_to: Optional[str] = None
    concept: Optional[str] = None
    file_type: Optional[str] = None
    contextual_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_recency(self) -> bool:
        return self.recency is not None

    @property
    def has_extension(self) -> bool:
        return self.extension is not None

    @property
    def has_location(self) -> bool:
        return self.location is not None

    @property
    def has_relative(self) -> bool:
        return self.relative_to is not None

    @property
    def has_concept(self) -> bool:
        return self.concept is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_text": self.original_text,
            "name_terms": list(self.name_terms),
            "extension": self.extension,
            "recency": self.recency,
            "location": self.location,
            "relative_to": self.relative_to,
            "concept": self.concept,
            "file_type": self.file_type,
            "metadata": dict(self.metadata),
        }


# =========================================================
# SEMANTIC QUERY PARSER
# =========================================================


class SemanticQueryParser:
    """
    Deterministic parser that extracts structured semantic preferences
    from natural-language file/folder target descriptions.

    This never accesses the filesystem. It only parses text.
    """

    VERSION = "3.8.5"

    # Recency patterns
    _RECENCY_PATTERNS: list[Tuple[str, str]] = [
        (r"\bnewest\b", "newest"),
        (r"\blatest\b", "latest"),
        (r"\bmost recent\b", "most_recent"),
        (r"\brecent\b", "recent"),
        (r"\byesterday\b", "yesterday"),
        (r"\btoday\b", "today"),
        (r"\blast week\b", "last_week"),
        (r"\blast month\b", "last_month"),
        (r"\bthis week\b", "this_week"),
        (r"\bthis month\b", "this_month"),
        (r"\bold(?:est)?\b", "oldest"),
        (r"\bfirst\b", "first"),
        (r"\blast\b", "last"),
    ]

    # Relative path patterns
    _RELATIVE_PATTERNS: list[Tuple[str, str]] = [
        (r"\bbeside\s+(?:the\s+)?(.+)", "beside"),
        (r"\bnext to\s+(.+)", "next_to"),
        (r"\bsame folder as\s+(.+)", "same_folder_as"),
        (r"\bin the same(?:\s+folder|\s+directory)?\s+as\s+(.+)", "same_folder_as"),
        (r"\bnear\s+(?:the\s+)?(.+)", "near"),
        (r"\boutside of\s+(.+)", "outside"),
        (r"\bwithin\s+(.+)", "within"),
    ]

    # Concept patterns
    _CONCEPT_PATTERNS: list[Tuple[str, str]] = [
        (r"\bthe original\b", "original"),
        (r"\bthe(?:ir)?\s+original\b", "original"),
        (r"\bthe copy\b", "copy"),
        (r"\bthe duplicate\b", "duplicate"),
        (r"\bthe backup\b", "backup"),
        (r"\bthe latest version\b", "latest_version"),
        (r"\bthe previous version\b", "previous_version"),
        (r"\bthe old version\b", "old_version"),
    ]

    # File type patterns (extensions that get mapped to semantic types)
    _FILE_TYPE_PATTERNS: list[Tuple[str, str]] = [
        (r"\bpdf\b", "pdf"),
        (r"\bspreadsheet\b", "spreadsheet"),
        (r"\bexcel\b", "spreadsheet"),
        (r"\bword\s*(?:doc(?:ument)?)?\b", "document"),
        (r"\bdoc(?:ument)?\b", "document"),
        (r"\bpresentation\b", "presentation"),
        (r"\bimage\b", "image"),
        (r"\bphoto(?:graph)?\b", "image"),
        (r"\bpicture\b", "image"),
        (r"\bvideo\b", "video"),
        (r"\baudio\b", "audio"),
        (r"\bmusic\b", "audio"),
        (r"\bartifact\b", "unknown"),
        (r"\bfile\b", None),
        (r"\bfiles\b", None),
        (r"\bdocument\b", "document"),
    ]

    # Contextual reference patterns (pronouns that need conversation history)
    _CONTEXTUAL_PATTERNS: list[Tuple[str, str]] = [
        (r"\bthat\s+file\b", "file"),
        (r"\bthis\s+file\b", "file"),
        (r"\bthe\s+file\b", "file"),
        (r"\bthat\s+folder\b", "folder"),
        (r"\bthis\s+folder\b", "folder"),
        (r"\bthe\s+folder\b", "folder"),
        (r"\bsame\s+folder\b", "folder"),
        (r"\bsame\s+directory\b", "folder"),
        (r"\bthat\s+directory\b", "folder"),
    ]

    def parse(self, text: str) -> ParsedSemanticQuery:
        """
        Parse a natural-language target description into structured preferences.
        """
        if not text or not text.strip():
            return ParsedSemanticQuery(original_text=text or "")

        cleaned = text.strip()
        lower = cleaned.lower()

        name_terms = self._extract_name_terms(lower)
        extension = self._extract_extension(lower)
        recency = self._extract_recency(lower)
        location = self._extract_location(lower)
        relative_to = self._extract_relative(lower)
        concept = self._extract_concept(lower)
        file_type = self._extract_file_type(lower, extension)
        contextual_reference = self._extract_contextual_reference(lower)

        return ParsedSemanticQuery(
            original_text=cleaned,
            name_terms=tuple(name_terms),
            extension=extension,
            recency=recency,
            location=location,
            relative_to=relative_to,
            concept=concept,
            file_type=file_type,
            contextual_reference=contextual_reference,
            metadata={"version": self.VERSION},
        )

    def _extract_name_terms(self, text: str) -> list[str]:
        """Extract meaningful name terms, stripping stop words and modifiers."""
        stop_words = frozenset({
            "my", "the", "a", "an", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "is", "it", "that", "this",
            "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could", "should",
            "may", "might", "shall", "can", "need", "dare", "ought",
            "used", "newest", "latest", "recent", "most", "recently",
            "oldest", "oldest", "biggest", "smallest", "largest",
            "first", "last", "next", "previous", "beside", "next",
            "folder", "directory", "file", "files", "doc", "document",
            "download", "downloads", "copy", "original", "backup",
            "and", "or", "then", "before", "after", "saved", "created",
        })

        tokens = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", text)
        terms = [
            t for t in tokens
            if t not in stop_words and len(t) > 1
        ]
        return terms

    def _extract_extension(self, text: str) -> Optional[str]:
        """Extract file extension from semantic type or literal extension."""
        for pattern, ext in [
            (r"\.pdf\b", ".pdf"),
            (r"\.xlsx?\b", ".xlsx"),
            (r"\.csv\b", ".csv"),
            (r"\.docx?\b", ".docx"),
            (r"\.pptx?\b", ".pptx"),
            (r"\.txt\b", ".txt"),
            (r"\.py\b", ".py"),
            (r"\.js\b", ".js"),
            (r"\.html\b", ".html"),
            (r"\.json\b", ".json"),
            (r"\.xml\b", ".xml"),
            (r"\.jpg\b", ".jpg"),
            (r"\.jpeg\b", ".jpeg"),
            (r"\.png\b", ".png"),
            (r"\.mp3\b", ".mp3"),
            (r"\.mp4\b", ".mp4"),
            (r"\.zip\b", ".zip"),
        ]:
            if re.search(pattern, text):
                return ext

        for keyword, ext in _KNOWN_EXTENSIONS.items():
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                return ext

        return None

    def _extract_recency(self, text: str) -> Optional[str]:
        """Extract recency preference from text."""
        for pattern, recency in self._RECENCY_PATTERNS:
            if re.search(pattern, text):
                return recency
        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """Extract location preference from text."""
        for alias, canonical in _LOCATION_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return canonical
        return None

    def _extract_relative(self, text: str) -> Optional[str]:
        """Extract relative path reference from text."""
        for pattern, _ in self._RELATIVE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_concept(self, text: str) -> Optional[str]:
        """Extract semantic concept (original, copy, etc.)."""
        for pattern, concept in self._CONCEPT_PATTERNS:
            if re.search(pattern, text):
                return concept
        return None

    def _extract_contextual_reference(self, text: str) -> Optional[str]:
        """Detect pronouns / contextual references that need conversation history.

        Returns "file" or "folder" indicating what the pronoun refers to,
        or None if no contextual reference is detected.
        """
        # Always check for strong contextual markers first
        for pattern, ref_type in self._CONTEXTUAL_PATTERNS:
            if re.search(pattern, text):
                # For mixed queries like "same folder tax return",
                # still return the ref_type — the provider will search
                # the resolved folder with the remaining name terms.
                return ref_type

        # Check for ambiguous pronouns: "open it", "that one", "get this"
        if _AMBIGUOUS_PRONOUN_RE.search(text):
            return "file"  # Ambiguous pronouns default to file context

        return None

    def _extract_file_type(
        self, text: str, extension: Optional[str]
    ) -> Optional[str]:
        """Extract semantic file type from text."""
        if extension:
            ext_to_type = {
                ".pdf": "pdf",
                ".xlsx": "spreadsheet",
                ".xls": "spreadsheet",
                ".csv": "spreadsheet",
                ".docx": "document",
                ".doc": "document",
                ".txt": "text",
                ".pptx": "presentation",
                ".ppt": "presentation",
                ".png": "image",
                ".jpg": "image",
                ".jpeg": "image",
                ".mp3": "audio",
                ".mp4": "video",
                ".zip": "archive",
                ".py": "code",
                ".js": "code",
                ".html": "web",
                ".json": "data",
                ".xml": "data",
            }
            if extension in ext_to_type:
                return ext_to_type[extension]

        for pattern, ftype in self._FILE_TYPE_PATTERNS:
            if re.search(pattern, text):
                return ftype

        return None


# Compiled regex for ambiguous pronouns (standalone "it", verb+it combos)
_AMBIGUOUS_PRONOUN_RE = re.compile(
    r"(?:^|\s)(?:open|read|write|copy|move|delete|rename|show|find|get|use)\s+it\b"
    r"|\bthat\s+one\b"
    r"|\bthis\s+one\b"
    r"|\bwhat\s+about\s+it\b"
    r"(?:^|\s)it(?:\s|$)",
    re.IGNORECASE,
)
