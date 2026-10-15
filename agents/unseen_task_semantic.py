"""
Genesis OS — Unseen Task Semantic Classifier.

Architectural role
------------------
This module is a deterministic, meaning-based classifier that runs
INSIDE the Level 3 decision pipeline. It catches whole FAMILIES of
natural-language requests that the existing regex patterns miss
because they were never enumerated during implementation.

It does NOT replace the WorkflowDecisionEngine. It is a
specialised detector that returns the same decision shape so the
existing ActionExecutor / workflow engine paths stay in charge.

Why a deterministic module (not the LLM fallback)?
--------------------------------------------------
The LLM semantic fallback in WorkflowDecisionEngine is optional,
rate-limited, and not always present. This module makes the
generalisation work OFFLINE and DETERMINISTICALLY by reasoning
about:

    * the user's verb family         (move / copy / delete / zip / ...)
    * the object family               (file / document / folder / archive / window)
    * the context / anaphora hints    ("the file I just edited", "the open document")
    * the structural shape            (compound "X and then Y", arithmetic "X% of Y")

It is intentionally NOT a list of hard-coded sentences. Each
pattern is a parametric grammar over verbs, objects, quantifiers
and prepositions.

Spec compliance
---------------
This module exists to close a real failure cluster measured on
unseen natural-language tasks. Every addition is paired with a
regression test that probes multiple paraphrases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


# =====================================================================
# LEXICON
# =====================================================================
#
# These are MEANING FAMILIES, not exact words. The classifier uses
# set membership to recognise synonyms and paraphrases.
# =====================================================================

_FILE_OBJECT_WORDS = frozenset({
    "file", "files", "document", "documents", "doc",
    "pdf", "spreadsheet", "sheet", "workbook",
    "presentation", "deck", "slides",
    "image", "images", "photo", "photos", "picture", "pictures",
    "video", "videos", "audio", "recording",
    "report", "reports", "essay", "essays",
    "attachment", "attachments",
})

_FOLDER_OBJECT_WORDS = frozenset({
    "folder", "folders", "directory", "directories",
    "stuff", "items", "things", "everything", "anything",
})

_ARCHIVE_OBJECT_WORDS = frozenset({
    "stuff", "items", "things", "files", "documents",
    "folder", "folders", "directory", "everything", "project",
    "project alpha", "project beta",
})

# Verbs grouped by meaning family.
_MOVE_VERBS = frozenset({
    "move", "put", "place", "transfer", "relocate", "shift",
})
_COPY_VERBS = frozenset({
    "copy", "duplicate", "clone", "save", "backup", "back up",
    "snapshot", "save a copy",
})
_DELETE_VERBS = frozenset({
    "delete", "remove", "trash", "discard", "erase",
})
_ZIP_VERBS = frozenset({
    "zip", "zip up", "zipped", "zipped up", "zipping",
    "compress", "compressed", "pack", "pack up", "packed",
    "package", "packaged", "package up", "bundled", "bundle up",
})
# "archive" / "archived" as VERBS are detected by a more
# specific pattern in _try_archive below rather than via
# the _ZIP_VERBS inclusion test, because "archive" also
# doubles as a NOUN ("a folder called Archive", "the
# archive folder"). Including it in _ZIP_VERBS causes the
# unseen classifier to hijack folder-create requests that
# happen to name the new folder "Archive".
_RENAME_VERBS = frozenset({
    "rename",
})
_OPEN_VERBS = frozenset({
    "open", "launch", "fire up", "bring up",
})
# NOTE: "start" is intentionally NOT in _OPEN_VERBS because
# it doubles as an authoring verb ("start writing", "start
# coding", "start the report"). The standard
# _detect_application_action path already handles bare
# "start <app>" launches correctly without false positives.
_CLOSE_VERBS = frozenset({
    "close", "quit", "exit", "shut", "shut down", "kill",
    "terminate", "end",
})

# Union of all file-op verbs. When one of these is present in
# the user's text, the standard-folder guard must not block
# anaphoric file detection.
_FILE_OP_VERBS = (
    _MOVE_VERBS
    | _COPY_VERBS
    | _DELETE_VERBS
    | _RENAME_VERBS
)
_PLAY_VERBS = frozenset({
    "play", "start playing", "resume", "queue up",
})
_MINIMIZE_VERBS = frozenset({
    "minimize", "minimise", "hide",
})
_RESTORE_VERBS = frozenset({
    "restore", "unminimize", "show", "bring back", "reopen",
})
_CLEAN_DESKTOP_VERBS = frozenset({
    "clean", "clear", "tidy", "tidy up",
})
_SHOW_DESKTOP_VERBS = frozenset({
    "show desktop", "see desktop", "go to desktop",
    "clean desktop", "tidy desktop",
})

# Connector words that signal a compound request.
_COMPOUND_CONNECTORS = (
    " and then ", " then ", " and also ", " plus ",
    " afterwards ", " after that ", " and ",
    " ; ", " , then ", " -- ",
)

# Prepositions that introduce a destination.
_DESTINATION_PREPOSITIONS = frozenset({
    "to", "into", "in", "onto", "on", "inside", "within",
})

# Determiners / references that signal an anaphoric or contextual
# reference to an existing file or folder.
_REFERENCE_DETERMINERS = frozenset({
    "the", "my", "this", "that", "these", "those", "our", "your",
})

# Words that signal "the thing I was just working on" or similar
# anaphoric references to the active document.
# IMPORTANT: only multi-word phrases are listed so bare verbs
# like "open" or adjectives like "active" do NOT trigger a
# file anaphora on their own (otherwise "open my downloads"
# would be misclassified as a file operation).
_ACTIVE_CONTEXT_WORDS = frozenset({
    "just edited", "just opened", "just modified", "just saved",
    "i was editing", "i was working on", "i was viewing",
    "i have open", "i had open", "currently open", "currently editing",
    "i was just working on", "we were looking at",
    "right now", "earlier today", "earlier", "yesterday", "last week",
})

# Destination words (where to put the file/folder).
_DESTINATION_NOUNS = frozenset({
    "desktop", "downloads", "documents", "pictures", "photos",
    "music", "videos", "reports", "projects", "workspace",
    "backup", "backups", "archive", "archives",
})


# =====================================================================
# DECISION DATACLASS
# =====================================================================


@dataclass(frozen=True)
class SemanticDecision:
    """A single decision produced by the classifier.

    Mirrors the shape of WorkflowDecisionEngine._decision so the
    caller can pass it through unchanged.
    """

    intent: str
    target: str
    confidence: float
    parameters: Dict[str, Any]
    description: str
    family: str  # diagnostic: which pattern family fired

    def as_decision_kwargs(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "target": self.target,
            "confidence": self.confidence,
            "parameters": dict(self.parameters),
            "description": self.description,
            "family": self.family,
        }


# =====================================================================
# HELPERS
# =====================================================================


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\s+", text.strip()) if t]


def _contains_any(text: str, words: Sequence[str]) -> bool:
    lowered = " " + text.lower() + " "
    for w in words:
        wl = w.lower()
        if " " in wl:
            if wl in lowered:
                return True
        else:
            if re.search(rf"\b{re.escape(wl)}\b", lowered):
                return True
    return False


def _extract_destination(text: str) -> Optional[str]:
    """Extract the destination noun-phrase from a text.

    Looks for a destination preposition followed by a noun from
    _DESTINATION_NOUNS (or a free-form single token, e.g. "the
    Reports folder").
    """
    lowered = text.lower()
    m = re.search(
        r"\b(?:to|into|in|onto|on|inside|within)\s+"
        r"(?:the\s+|my\s+)?([a-zA-Z][\w \-]{0,30}?)(?:\s+folder|\s+directory|\.|$|,)",
        lowered,
    )
    if not m:
        return None
    dest = m.group(1).strip(" -")
    if not dest:
        return None
    return dest


# Standard Windows user folders that the OS opens by name.
# An anaphoric file operation must NOT fire when the user is
# clearly referring to one of these canonical folders.
_STANDARD_USER_FOLDERS = frozenset({
    "downloads", "download", "documents", "document", "docs",
    "desktop", "pictures", "photos", "music", "videos",
    "projects", "workspace", "reports", "backups", "backup",
})

# Nouns that are ambiguous between a file and a folder. We only
# count them as file references when the text is NOT clearly
# targeting a standard user folder.
_AMBIGUOUS_FILE_NOUNS = frozenset({
    "document", "documents", "file", "files",
})


def _looks_like_standard_user_folder(text: str) -> bool:
    """True when the text is clearly opening/closing/moving a
    standard Windows user folder rather than an anaphoric file.
    """
    lowered = text.lower()
    # Look for a standard folder name as a standalone token.
    for folder in _STANDARD_USER_FOLDERS:
        if re.search(rf"\b{re.escape(folder)}\b", lowered):
            # AND the verb is a folder verb, not a file verb
            # like "delete" / "rename" / "inspect".
            folder_verbs = {
                "open", "launch", "show", "explore", "navigate",
                "go", "take", "see", "browse", "visit", "visit",
            }
            first_word = lowered.split()[0] if lowered.split() else ""
            if first_word in folder_verbs:
                return True
            # Also catch "go to my downloads" etc.
            if any(v in lowered.split() for v in folder_verbs):
                return True
    return False


def _is_anaphoric_file_ref(text: str) -> bool:
    """Return True if text contains a contextual reference to
    an existing/active file rather than a concrete name.

    Examples that return True:
        "the file I just edited"
        "the document I have open"
        "the open pdf"
        "the spreadsheet I was working on yesterday"
    Examples that return False:
        "open my downloads folder"   (canonical folder)
        "close my downloads"         (canonical folder)
        "open chrome"                (proper application name)
        "show me the downloads"      (canonical folder)
        "open my essay.docx"         (specific filename
                                       with extension — not
                                       anaphoric)
    """
    lowered = text.lower()
    if not _contains_any(lowered, _REFERENCE_DETERMINERS):
        return False
    # A specific filename with a file extension is NOT
    # anaphoric. "open my essay.docx" names a specific file;
    # the runtime opens it directly.
    if re.search(
        r"\b[\w\s_-]+\.[a-z0-9]{1,8}\b",
        lowered,
    ):
        return False
    # File op verbs (copy, delete, move, rename) always take
    # priority over the standard-folder guard, because "save a
    # copy of the open pdf onto my desktop" is unambiguously a
    # file copy, not a folder open.
    if _contains_any(lowered, _FILE_OP_VERBS):
        if _contains_any(lowered, _FILE_OBJECT_WORDS):
            return True
    # A standard user folder is not an anaphoric file when
    # the user is just opening/showing it.
    if _looks_like_standard_user_folder(lowered):
        return False
    # Require a concrete file-family noun. Folder nouns and
    # bare verbs like "open" must not by themselves trigger
    # anaphoric file detection.
    if _contains_any(lowered, _FILE_OBJECT_WORDS):
        return True
    return False


def _is_anaphoric_folder_ref(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(lowered, _REFERENCE_DETERMINERS) and (
        _contains_any(lowered, _FOLDER_OBJECT_WORDS)
        or _contains_any(lowered, _ACTIVE_CONTEXT_WORDS)
    )


def _is_compound(text: str) -> bool:
    lowered = " " + text.lower().strip() + " "
    return any(c in lowered for c in _COMPOUND_CONNECTORS)


# =====================================================================
# PATTERN FAMILIES
# =====================================================================


def _try_anaphoric_file_op(text: str) -> Optional[SemanticDecision]:
    """Pattern: anaphoric file reference + file op verb.

    Examples:
        "put the file I just edited into the Reports folder"
        "move my active document to the desktop"
        "save a copy of the open pdf onto my desktop"
        "delete that file we were looking at"
    """
    lowered = text.lower()
    if not _is_anaphoric_file_ref(lowered):
        return None

    if _contains_any(lowered, _MOVE_VERBS):
        dest = _extract_destination(lowered) or ""
        params = {
            "destination": dest,
            "source_is_anaphoric": True,
            "requires_confirmation": True,
            "confirmed": False,
        }
        if not dest:
            params["requires_target"] = True
        return SemanticDecision(
            intent="file.move",
            target=dest,
            confidence=0.91,
            parameters=params,
            description=(
                "Anaphoric file move: move the referenced "
                "file into the requested destination."
            ),
            family="anaphoric_file_move",
        )

    if _contains_any(lowered, _COPY_VERBS):
        dest = _extract_destination(lowered) or ""
        params = {
            "destination": dest,
            "source_is_anaphoric": True,
            "requires_confirmation": True,
            "confirmed": False,
        }
        if not dest:
            params["requires_target"] = True
        return SemanticDecision(
            intent="file.copy",
            target=dest,
            confidence=0.91,
            parameters=params,
            description=(
                "Anaphoric file copy: copy the referenced "
                "file into the requested destination."
            ),
            family="anaphoric_file_copy",
        )

    if _contains_any(lowered, _DELETE_VERBS):
        return SemanticDecision(
            intent="file.delete",
            target="",
            confidence=0.91,
            parameters={
                "source_is_anaphoric": True,
                "requires_confirmation": True,
                "confirmed": False,
                "requires_target": True,
            },
            description=(
                "Anaphoric file delete: delete the "
                "referenced file (confirmation required)."
            ),
            family="anaphoric_file_delete",
        )

    if _contains_any(lowered, _RENAME_VERBS):
        return SemanticDecision(
            intent="file.rename",
            target="",
            confidence=0.90,
            parameters={
                "source_is_anaphoric": True,
                "requires_confirmation": True,
                "confirmed": False,
                "requires_target": True,
            },
            description="Anaphoric file rename.",
            family="anaphoric_file_rename",
        )

    if _contains_any(lowered, _OPEN_VERBS):
        # Determine whether the noun is a specific file
        # family (spreadsheet, PDF, document, etc.) and
        # route to the corresponding L3 family intent
        # (spreadsheet.inspect, document.read) instead of
        # the generic file.open. "open the latest marks
        # spreadsheet" should not collapse to file.open.
        family_intent = None
        family = None
        for fam_word, fam_intent_str in (
            (("spreadsheet", "sheet", "workbook"), "spreadsheet.inspect"),
            (("pdf", "docx", "doc", "document"), "document.read"),
            (("presentation", "pptx", "ppt"), "document.read"),
            (("image", "photo", "picture", "video"), "file.open"),
        ):
            if any(w in lowered for w in fam_word):
                family_intent = fam_intent_str
                family = fam_word[0]
                break
        if family_intent is not None:
            return SemanticDecision(
                intent=family_intent,
                target="",
                confidence=0.92,
                parameters={
                    "source_is_anaphoric": True,
                    "requires_target": True,
                    "document_kind": family,
                },
                description=(
                    f"Anaphoric {family} reference: the user "
                    "asked to open the 'latest X' where X is "
                    "a specific file family. The runtime entity "
                    "binder must resolve the actual file."
                ),
                family="anaphoric_file_open_family",
            )
        return SemanticDecision(
            intent="file.open",
            target="",
            confidence=0.91,
            parameters={
                "source_is_anaphoric": True,
                "requires_target": True,
            },
            description=(
                "Anaphoric file open: open the referenced "
                "file from the current session."
            ),
            family="anaphoric_file_open",
        )

    return None


def _try_math_nl(text: str) -> Optional[SemanticDecision]:
    """Pattern: natural-language arithmetic without explicit
    "calculate" keyword.

    Examples:
        "what is 17% of 2450 and add it to 800"
        "17 percent of 2450"
        "2450 plus 800"
        "what is 100 divided by 4"
        "25 times 4"
    """
    lowered = text.lower().strip()

    # Strip leading question phrases, please, i need, etc.
    stripped = re.sub(
        r"^(?:please\s+|i\s+need\s+(?:to\s+)?|i\s+want\s+(?:to\s+)?)?"
        r"(?:what(?:'s| is)?|compute|calculate|solve|figure\s+out|"
        r"can\s+you\s+(?:calculate|compute|solve)|how\s+much\s+is)\s+",
        "",
        lowered,
    ).strip(" ?.,!")

    # "X% of Y" / "X percent of Y" — possibly with a trailing
    # "and add/subtract/multiply/divide Z" or "plus/minus/times Z".
    m = re.match(
        r"^\s*(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(\d+(?:\.\d+)?)"
        r"(?:\s+(?:and|then|plus|and\s+then)\s+"
        r"(?:add|subtract|multiply|divide|times)?\s*"
        r"(?:it\s+)?(?:to|from|by)?\s*(\d+(?:\.\d+)?))?\s*$",
        stripped,
    )
    if m:
        pct = float(m.group(1))
        base = float(m.group(2))
        extra = m.group(3)
        expr = f"({pct}/100)*{base}"
        if extra is not None:
            tail = stripped
            if "subtract" in tail or "minus" in tail or "less" in tail:
                expr = f"{expr}-{extra}"
            elif (
                "multiply" in tail
                or "times" in tail
                or re.search(r"\bx\b", tail)
            ):
                expr = f"{expr}*{extra}"
            elif "divide" in tail:
                expr = f"{expr}/{extra}"
            else:
                expr = f"{expr}+{extra}"
        return SemanticDecision(
            intent="math.evaluate",
            target=expr,
            confidence=0.93,
            parameters={"expression": expr},
            description="Evaluate the arithmetic expression.",
            family="math_nl_percent",
        )

    # "X percent" alone.
    m_pct_only = re.match(
        r"^\s*(\d+(?:\.\d+)?)\s+percent(?:\s+of\s+(\d+(?:\.\d+)?))?\s*$",
        stripped,
    )
    if m_pct_only:
        pct = float(m_pct_only.group(1))
        base = float(m_pct_only.group(2)) if m_pct_only.group(2) else 100.0
        expr = f"({pct}/100)*{base}"
        return SemanticDecision(
            intent="math.evaluate",
            target=expr,
            confidence=0.92,
            parameters={"expression": expr},
            description="Evaluate the percentage.",
            family="math_nl_percent",
        )

    # Plain arithmetic: "2450 + 800", "100 divided by 4",
    # "25 times 4", "what is 9 * 9".
    m2 = re.match(
        r"^\s*(?:what(?:'s| is)?\s+)?"
        r"(\d+(?:\.\d+)?\s*(?:\+|\-|\*|/|\bx\b|times|divided\s+by|plus|minus)\s*\d+(?:\.\d+)?"
        r"(?:\s*(?:\+|\-|\*|/|\bx\b|times|divided\s+by|plus|minus)\s*\d+(?:\.\d+)?)*)\s*$",
        stripped,
    )
    if m2:
        expr_raw = m2.group(1)
        # Normalise natural-language operators to symbols.
        expr = expr_raw
        expr = re.sub(r"\bplus\b", "+", expr)
        expr = re.sub(r"\bminus\b", "-", expr)
        expr = re.sub(r"\btimes\b", "*", expr)
        expr = re.sub(r"\bx\b", "*", expr)
        expr = re.sub(r"\bdivided\s+by\b", "/", expr)
        expr = re.sub(r"\s+", "", expr)
        if re.fullmatch(r"[\d\.\+\-\*/\(\)]+", expr):
            return SemanticDecision(
                intent="math.evaluate",
                target=expr,
                confidence=0.92,
                parameters={"expression": expr},
                description="Evaluate the arithmetic expression.",
                family="math_nl_arithmetic",
            )

    return None


def _try_window_idiom(text: str) -> Optional[SemanticDecision]:
    """Pattern: window/desktop control idioms not covered by
    the existing minimal patterns.

    Examples:
        "shut everything down and give me a clean desktop"
        "hide everything"     -> minimize_all
        "clean up the desktop" -> show_desktop
        "show me the desktop"  -> show_desktop
        "i want to see my desktop" -> show_desktop
    """
    lowered = text.lower().strip()

    # show_desktop idioms (the existing pattern is only "show my desktop").
    show_dt = re.match(
        r"^(?:please\s+)?(?:"
        r"show\s+me\s+(?:the|my)\s+desktop|"
        r"i\s+want\s+to\s+see\s+(?:the|my)\s+desktop|"
        r"clean\s+(?:up\s+)?(?:the|my)\s+desktop|"
        r"tidy\s+(?:up\s+)?(?:the|my)\s+desktop|"
        r"(?:give|get)\s+me\s+(?:a\s+)?clean\s+desktop"
        r")\s*[?.]?$",
        lowered,
    )
    if show_dt:
        return SemanticDecision(
            intent="window.show_desktop",
            target="desktop",
            confidence=0.95,
            parameters={},
            description="Show the desktop by minimising all windows.",
            family="window_show_desktop",
        )

    # minimize_all idioms.
    min_all = re.match(
        r"^(?:please\s+)?(?:"
        r"hide\s+everything|"
        r"hide\s+all\s+(?:the\s+)?windows?|"
        r"clear\s+(?:my\s+)?desktop|"
        r"shut\s+everything\s+down(?:\s+and\s+give\s+me\s+a\s+clean\s+desktop)?"
        r")\s*[?.]?$",
        lowered,
    )
    if min_all:
        return SemanticDecision(
            intent="window.minimize_all",
            target="windows",
            confidence=0.95,
            parameters={},
            description="Minimise every open window.",
            family="window_minimize_all",
        )

    # restore idioms.
    restore = re.match(
        r"^(?:please\s+)?(?:"
        r"bring\s+(?:the\s+|my\s+|all\s+(?:the\s+)?)?windows?\s+back|"
        r"unhide\s+(?:all\s+(?:the\s+)?)?windows?|"
        r"show\s+(?:all\s+(?:the\s+)?)?windows?\s+again"
        r")\s*[?.]?$",
        lowered,
    )
    if restore:
        return SemanticDecision(
            intent="window.restore",
            target="windows",
            confidence=0.94,
            parameters={},
            description="Restore all minimised windows.",
            family="window_restore",
        )

    return None


def _try_archive(text: str) -> Optional[SemanticDecision]:
    """Pattern: archive / zip-up requests.

    Examples:
        "zip up everything related to Project Alpha"
        "compress the downloads folder"
        "archive my documents"
        "pack the photos into an archive"
        "I need everything related to Project Alpha zipped up"

    The verb "archive" is matched as a whole word so that
    folder names that happen to be "Archive" (e.g. "make a
    folder named Archive") do NOT trigger this path.
    """

    lowered = text.lower()

    # "make a folder named Archive" / "create folder Archive" /
    # any request whose purpose is to CREATE a folder whose
    # name is "Archive" — these are folder.create, not
    # archive operations. Guard before checking the archive
    # verb set so the unseen classifier never hijacks them.
    if re.search(
        r"\b(?:make|create|new)\s+(?:a\s+|an\s+)?(?:new\s+)?"
        r"folder\s+(?:named|called|for)\b",
        lowered,
    ):
        return None

    # Verb test: include "archive" / "archived" as whole-word
    # matches, plus the unambiguous _ZIP_VERBS list.
    archive_verb = re.search(
        r"\b(?:archive|archived|archiving|zip|zip\s+up|"
        r"zipped|zipping|compress|compressed|compress\s+up|"
        r"pack(?:\s+up)?|packed|package(?:\s+up)?|"
        r"packaged|bundle(?:\s+up)?|bundled)\b",
        lowered,
    )
    if not archive_verb:
        return None

    # ITEM 21 (ledger): a verb plus a BARE generic noun names no
    # object. "archive folder", "archive the folder", "zip drive" all
    # satisfy the verb test and the object-word test below (the word
    # "folder" is itself an archive object word), yet none of them says
    # what to archive — which is how "archive folder" produced a
    # confident 0.91 folder.organize with an empty target.
    #
    # Every legitimate request in this family names a referent:
    #   "archive my documents"          -> possessive
    #   "compress the downloads folder" -> determiner + modifier
    #   "zip up everything related to Project Alpha" -> quantifier + proper noun
    #   "pack the photos into an archive" -> determiner + PP
    # So the test is whether a referent survives once the verb is
    # removed, not whether a particular word appeared.
    #
    # Stated over the SHAPE (verb + bare generic noun), not over the
    # word "archive", so a future synonym added to the verb set above
    # is judged by the same rule.
    _remainder = lowered[archive_verb.end():].strip(" .?!")
    if re.fullmatch(
        r"(?:the\s+|a\s+|an\s+)?"
        r"(?:folders?|drives?|files?|documents?|photos?|images?|"
        r"videos?|notes?|backups?|archives?|stuff|things?)",
        _remainder,
    ):
        return None

    if not (
        _contains_any(lowered, _ARCHIVE_OBJECT_WORDS)
        or "everything related to" in lowered
        or "anything related to" in lowered
        or "all my" in lowered
        or "all the" in lowered
        or "into an archive" in lowered
        or "into a zip" in lowered
        or re.search(r"\bproject\s+\w+", lowered) is not None
    ):
        return None
    return SemanticDecision(
        intent="folder.organize",
        target="",
        confidence=0.91,
        parameters={
            "operation": "archive",
            "requires_confirmation": True,
            "confirmed": False,
            "requires_target": True,
        },
        description=(
            "Archive the referenced files or folder "
            "(confirmation required; target will be "
            "resolved at execution time)."
        ),
        family="archive_zip",
    )


# =====================================================================
# PUBLIC API
# =====================================================================


class UnseenTaskSemanticClassifier:
    """Deterministic semantic classifier for unseen Level 3 phrasings.

    The classifier is intentionally order-independent in design but
    the order of checks is chosen so the most specific patterns
    (anaphoric, compound) fire before the broader fallbacks.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._families: List[str] = []

    def classify(self, text: str) -> Optional[SemanticDecision]:
        """Return a SemanticDecision if the text matches a known
        family, else None.

        The classifier is read-only and side-effect free.
        """
        if not text or not text.strip():
            return None

        self._families = []

        # 1) Anaphoric file operations must come first because they
        #    may overlap with folder/organize patterns.
        dec = _try_anaphoric_file_op(text)
        if dec is not None:
            self._families.append(dec.family)
            return dec

        # 2) Archive / zip-up requests.
        dec = _try_archive(text)
        if dec is not None:
            self._families.append(dec.family)
            return dec

        # 3) Window / desktop idioms.
        dec = _try_window_idiom(text)
        if dec is not None:
            self._families.append(dec.family)
            return dec

        # 4) Math natural language.
        dec = _try_math_nl(text)
        if dec is not None:
            self._families.append(dec.family)
            return dec

        return None

    @property
    def last_families(self) -> List[str]:
        return list(self._families)
