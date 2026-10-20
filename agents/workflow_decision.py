"""
Genesis OS
Workflow Decision Engine

Version:
    3.2

Responsibilities:
    Level 1 — Conversation
    Level 2 — Specialized Agent Workflows
    Level 3 — AI Operating System

Level 3.2:
    Application Intelligence

Architecture:

    User
      ↓
    WorkflowDecisionEngine
      ↓
    GenesisOS
      ↓
    OSManager
      ↓
    ApplicationManager
      ↓
    Operating System

IMPORTANT:
    This module decides WHAT Genesis should do.

    It does NOT execute operating-system actions.

Maturity goals:
    - Strong OS intent detection
    - Low false-positive rate
    - Natural-language application commands
    - Application target validation
    - Safe status-question detection
    - Deterministic routing
    - Explainable decisions
    - Future-ready Level 3 expansion
"""

# =========================================================
# IMPORTS
# =========================================================

import json
import re
from difflib import get_close_matches
from typing import Any, Dict, List, Optional


# =========================================================
# ITEM 18B (L17) — KEYWORD WORD-BOUNDARY MATCHING
#
# Routing keywords used to be tested with a raw substring
# check (`keyword in text`), so short keys matched inside
# larger words: "ui" fires in "build", "circuit", "guide"
# and "quick", spuriously selecting the design agent for
# requests that never mention design. Keywords now match
# only on word boundaries (compiled \b-anchored pattern),
# so a standalone token ("make a ui mockup") still matches
# while the inside-of-a-word hits do not. Patterns are
# compiled once and cached per keyword.
# =========================================================

_KEYWORD_PATTERN_CACHE: Dict[str, Any] = {}


def _keyword_pattern(keyword: str) -> Any:
    """Compiled \b-anchored pattern for a routing keyword."""
    pattern = _KEYWORD_PATTERN_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(
            r"\b" + re.escape(keyword) + r"\b"
        )
        _KEYWORD_PATTERN_CACHE[keyword] = pattern
    return pattern


# =========================================================
# EXTENDED INTENT PATTERNS
#
# Compiled once so that normalized matching and
# case-preserving target extraction always stay identical.
# =========================================================

_FOLDER_CREATE_RE = re.compile(
    r"(?:create|make|new)\s+(?:a\s+|an\s+)?(?:new\s+)?folder\s+"
    r"(?:for\s+(?:my\s+)?|named\s+|called\s+)?['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)

_FOLDER_OPEN_EXPLICIT_RE = re.compile(
    r"(?:open|explore)\s+(?:the\s+)?folder\s+['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)

# "save X to my Y folder" / "save X in my Y folder" /
# "save X to the Y folder". The natural Level-3 intent is
# folder.create so the executor ensures the folder exists
# before the L2 agent's output is written into it. Without
# this pattern the second clause of a mixed L2+L3 request
# ("research biology and save the result to my Biology
# folder") collapses to L1 conversation because none of
# the existing folder regexes match the "save ... to my
# <name> folder" shape.
_SAVE_TO_FOLDER_RE = re.compile(
    r"^(?:please\s+)?(?:save|write|put|store|place|copy|drop|"
    r"add|append|export|output|land|file|log|record|note)"
    r"(?:\s+(?:it|the\s+(?:result|output|finding|answer|report|"
    r"summary|file|document|data|response)|"
    r"(?:the\s+)?(?:result|output|finding|answer|report|"
    r"summary|file|document|data|response)s?|this|that|these|"
    r"those|everything|all\s+(?:of\s+)?it|"
    r"(?:the\s+)?(?:new|latest|fresh)\s+\w+))?"
    r"\s+(?:to|in(?:to)?|inside|within|under|on)\s+"
    r"(?:my|the|our|your|a|an)?\s*"
    r"['\"]?(.+?)['\"]?\s+folder\s*[.?!]?$",
    re.IGNORECASE,
)

_SAVE_AS_PDF_RE = re.compile(
    r"^(?:please\s+)?(?:save|export|write|store)\s+"
    r"(?:it|the\s+(?:result|output|finding|answer|report|summary|response)|"
    r"(?:the\s+)?result|(?:the\s+)?output|this|that)?\s*"
    r"(?:as|to)\s+(?:an?\s+)?pdf(?:\s+file)?[.?!]?$",
    re.IGNORECASE,
)

_MOVE_FILES_RE = re.compile(
    r"move\s+(?:these\s+|the\s+)?files?\s+(?:in|into|to)\s+"
    r"(?:the\s+)?(?:folder\s+)?['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)

_NATURAL_OPEN_FILE_RE = re.compile(
    r"open\s+(?:the\s+|my\s+)?(pdf|document|file|presentation|essay|spreadsheet|sheet)\s+(.+)$",
    re.IGNORECASE,
)

# =========================================================
# GUI TYPE / CLICK / PASTE PATTERNS
# ------------------------------------------------------------
# These natural phrasings have NO file-system target and
# no application-installation semantic — they describe an
# interaction with a focused window ("type Hello into
# notepad"). They map onto the Level-3 gui.* capabilities
# defined in genesis_os/capability_registry.py so the
# executor's GUIController can drive pyautogui.
#
# The pattern intentionally accepts:
#   * Quoted text: write "Hello World" in notepad
#   * Unquoted text: type Hello from Genesis
#   * Optional "in|into <window>": write Hello in notepad
# When no window is named, target=None ("type into whatever
# window currently has focus").
# =========================================================
_GUI_TYPE_TEXT_RE = re.compile(
    r"^(?:please\s+)?(?:"
    # write/type/enter text/input/fill in
    r"write|type|enter\s+text|input|fill\s+in|paste"
    r")\s+"
    r"(?:"
    r"\"(?P<qtext>[^\"]+)\""
    r"|'(?P<stext>[^']+)'"
    r"|(?P<utext>.+?)"
    r")"
    r"(?:\s+(?:in|into|inside|within|to)\s+(?P<target>.+?))?"
    r"\s*$",
    re.IGNORECASE,
)

# =========================================================
# LEVEL 3.10 UNIVERSAL DESKTOP CONTROL PATTERNS
# =========================================================

_SCREENSHOT_RE = re.compile(
    r"(?:take\s+|capture\s+|grab\s+)?(?:a\s+)?(?:screen\s?shot|screenshot|"
    r"picture\s+of\s+my\s+screen|capture\s+the\s+screen)",
    re.IGNORECASE,
)

_MEDIA_ACTION_RE = re.compile(
    r"^(?:please\s+)?(?:(?:play|resume)(?:\s+(?:some\s+)?music|it)?|pause(?:\s+music|it)?|"
    r"stop\s+the?\s*music|stop\s+playing|next\s+(?:track|song|video)|"
    r"skip\s+(?:this\s+)?(?:track|song)|previous\s+(?:track|song)|"
    r"go\s+back\s+a\s+track|play)\b",
    re.IGNORECASE,
)

_VOLUME_RE = re.compile(
    r"^(?:turn\s+|set\s+)?(?:the\s+)?volume\s+"
    r"(up|down|max|full|mute|unmute|silent)"
    r"(?:\s+(?:a\s+bit|a\s+little))?$",
    re.IGNORECASE,
)

_VOLUME_SET_RE = re.compile(
    r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to|at)\s+(\d{1,3})\s*(?:percent|%)?$",
    re.IGNORECASE,
)

_BRIGHTNESS_SET_RE = re.compile(
    r"^(?:set\s+)?(?:the\s+)?brightness\s+(?:to|at)\s+(\d{1,3})\s*(?:percent|%)?$",
    re.IGNORECASE,
)

_BRIGHTNESS_STEP_RE = re.compile(
    r"^(?:turn\s+|make\s+)?(?:the\s+)?brightness\s+(up|down)$",
    re.IGNORECASE,
)

_BATTERY_RE = re.compile(
    r"(?:battery|charge)(?:\s+(?:level|status|percentage|life|level\?|status\?))?"
    r"|\bhow\s+much\s+battery\b",
    re.IGNORECASE,
)

_SYSTEM_PERF_RE = re.compile(
    r"\b(?:cpu|memory|ram|system\s+performance|pc\s+performance|"
    r"computer\s+performance|how\s+is\s+my\s+(?:pc|computer|system)\b)",
    re.IGNORECASE,
)

_CLIPBOARD_COPY_RE = re.compile(
    r"^copy\s+(.+?)\s+to\s+(?:the\s+)?clipboard$|^clip\s+(.+)$",
    re.IGNORECASE,
)

_CLIPBOARD_READ_RE = re.compile(
    r"^(?:what(?:'s|s| is)\s+(?:in|on)\s+(?:the\s+)?clipboard|"
    r"read\s+(?:the\s+)?clipboard|paste\s+from\s+clipboard|show\s+clipboard|"
    r"(?:show|open)\s+(?:the\s+)?clipboard)$",
    re.IGNORECASE,
)

_BARE_MUTE_RE = re.compile(
    r"^(?:please\s+)?(mute|unmute)(?:\s+(?:the\s+)?(?:volume|audio|sound))?$",
    re.IGNORECASE,
)

# =========================================================
# LEVEL 3.12 WEBSITES / WINDOWS / DAILY PATTERNS
# =========================================================

_SITE_ALIASES = {
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "chatgpt": "https://chat.openai.com",
    "linkedin": "https://www.linkedin.com",
    "twitch": "https://www.twitch.tv",
    "spotify web": "https://open.spotify.com",
    "wikipedia": "https://www.wikipedia.org",
}

_OPEN_SITE_RE = re.compile(
    r"^(?:open|go\s+to|visit|launch)\s+(?:the\s+)?([a-z][a-z ]{1,20}?)"
    r"(?:\s+(?:website|site))?$",
    re.IGNORECASE,
)

_PLAY_ON_YOUTUBE_RE = re.compile(
    r"^play\s+(.+?)\s+on\s+youtube$|^youtube\s+(.+?)$",
    re.IGNORECASE,
)

_WINDOW_OPS = {
    r"^(?:minimize|minimise)\s+(?:all\s+)?(?:the\s+)?windows?$": (
        "window.minimize_all", "minimize_all", "Minimize every open window."
    ),
    r"^show\s+(?:my\s+)?desktop$": (
        "window.show_desktop", "show_desktop", "Toggled desktop visibility."
    ),
    r"^(?:restore|unminimize)\s+(?:all\s+)?(?:the\s+)?windows?$": (
        "window.restore", "restore", "Windows restored."
    ),
}

_STORAGE_RE = re.compile(
    r"\b(storage|disk\s+space|hard\s+drive|free\s+space)\b",
    re.IGNORECASE,
)

_WEATHER_RE = re.compile(
    r"^(?:what(?:'s| is)\s+the\s+)?weather(?:\s+(?:like)?)?\s*"
    r"(?:in|for|at)\s+(?P<city>[a-zA-Z\u00C0-\u024F ]+?)\s*[?.]?$"
    r"|^weather\s+(?:in\s+|for\s+)?(?P<city2>[a-zA-Z\u00C0-\u024F ]+?)\s*[?.]?$",
    re.IGNORECASE,
)

_WORLD_CLOCK_RE = re.compile(
    r"^(?:what\s+time\s+is\s+it(?:\s+right\s+now)?|what(?:'s|s| is)\s+the\s+time)"
    r"\s+(?:in|at)\s+(?P<city>[a-zA-Z ]+?)\s*[?.]?$"
    r"|^time\s+(?:in|at)\s+(?P<city2>[a-zA-Z ]+?)\s*[?.]?$",
    re.IGNORECASE,
)

_MATH_RE = re.compile(
    r"^(?:calculate|compute|solve|what(?:'s| is))\s+(?P<expr>.+)$",
    re.IGNORECASE,
)

_PERCENT_OF_RE = re.compile(
    r"^\s*(?P<pct>\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(?P<num>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)

_NOTE_CREATE_RE = re.compile(
    r"^(?:create|make|save|add)\s+(?:a\s+|an\s+)?(?:new\s+|quick\s+|short\s+)?"
    r"note[:\s]+(?P<text>.+)$"
    r"|^note\s*[:\-]\s*(?P<text2>.+)$",
    re.IGNORECASE,
)

# "Remember that X" / "Remember to X" are L1 long-term memory
# operations (the user is asking the AI to store a fact
# about them), NOT notes.create. The notes.create path is
# for explicit note-taking ("create a note: buy milk",
# "save a note: ..."). This split is mandated by the
# directive's memory model: long-term memory is a Level 1
# concern; the notes subsystem is a Level 3 OS concern.
_REMEMBER_RE = re.compile(
    r"^remember\s+(?:that\s+)?(?P<text>.+)$"
    r"|^remember\s+to\s+(?P<text2>.+)$",
    re.IGNORECASE,
)

_NOTES_LIST_RE = re.compile(
    r"^(?:read|show|list|see)(?:\s+my)?\s+notes?$|"
    r"^what\s+are\s+my\s+notes[?]?$|"
    r"^do\s+i\s+have\s+(?:any\s+)?notes[?]?$",
    re.IGNORECASE,
)

_INSTALL_RE = re.compile(
    r"^(?:install|uninstall)\s+(?P<package>[a-z0-9 .+\-_]+?)"
    r"(?:\s+(?:for\s+me|app|application|program))?$",
    re.IGNORECASE,
)

_RECYCLE_BIN_RE = re.compile(
    r"^(?:empty|clear|wipe)\s+(?:the\s+)?recycle\s?bin$|"
    r"^delete\s+(?:everything|all)\s+in\s+(?:the\s+)?recycle\s?bin$",
    re.IGNORECASE,
)

_RECYCLE_QUERY_RE = re.compile(
    r"^(?:what(?:'s|s| is)\s+in\s+(?:the\s+)?recycle\s?bin|"
    r"how\s+(?:much|many)\s+(?:stuff\s+)?(?:is|items are)\s+in\s+(?:the\s+)?recycle\s?bin)\s*[?]?$",
    re.IGNORECASE,
)

# Concept-level synonyms: users express the SAME underlying
# control through different words. These map MEANING onto
# capabilities without requiring exact phrases.
_CONCEPT_SYNONYMS = (
    # Brightness family
    (
        re.compile(
            r"\b(brighter|more\s+bright|brighten|increase\s+(?:the\s+)?brightness)\b",
            re.IGNORECASE,
        ),
        "up",
    ),
    (
        re.compile(
            r"\b(dimmer|darker|dim\s+(?:the\s+)?(?:screen|display)?|"
            r"darken|decrease\s+(?:the\s+)?brightness|lower\s+(?:the\s+)?brightness)\b",
            re.IGNORECASE,
        ),
        "down",
    ),
    # Volume family
    (
        re.compile(r"\b(louder|loudest|increase\s+(?:the\s+)?volume|raise\s+(?:the\s+)?volume)\b",
                   re.IGNORECASE),
        "volume_up",
    ),
    (
        re.compile(r"\b(quieter|softer|lower\s+(?:the\s+)?volume|decrease\s+(?:the\s+)?volume)\b",
                   re.IGNORECASE),
        "volume_down",
    ),
    (
        re.compile(r"\b(kill\s+(?:the\s+)?(?:sound|audio)|silence|shut\s+off\s+(?:the\s+)?sound)\b",
                   re.IGNORECASE),
        "mute",
    ),
)

_LOCK_WORKSTATION_RE = re.compile(
    r"^lock\s+(?:my\s+|the\s+)?(?:computer|pc|workstation|windows|session)$",
    re.IGNORECASE,
)

# Politeness / question lead-ins. The OS decision layer
# must handle natural, polite phrasings ("could you open
# chrome please", "I'd like to see my documents", "can you
# launch the settings") without the LLM fallback, because
# the OS layer is the primary response path for these.
#
# Stripping these prefixes once, centrally, keeps every
# existing pattern simple and prevents the conversational
# guard from hijacking genuine OS requests.
_POLITENESS_PREFIX_RE = re.compile(
    r"^(?:"
    r"please\s+|"
    r"please\s+can\s+you\s+|"
    r"could\s+you\s+(?:please\s+)?|"
    r"can\s+you\s+(?:please\s+)?|"
    r"would\s+you\s+(?:please\s+)?(?:mind\s+to\s+|be\s+so\s+kind\s+as\s+to\s+)?|"
    r"i\s+would\s+like\s+(?:you\s+)?to\s+|"
    r"i\s+would\s+like\s+|"
    r"i'd\s+like\s+(?:you\s+)?to\s+|"
    r"i'd\s+like\s+|"
    r"i\s+want\s+(?:you\s+)?to\s+|"
    r"i\s+want\s+|"
    r"i\s+need\s+(?:you\s+)?to\s+|"
    r"i\s+need\s+|"
    r"let's\s+|"
    r"let\s+us\s+|"
    r"do\s+me\s+a\s+favour\s+and\s+|"
    r"do\s+me\s+a\s+favor\s+and\s+"
    r")",
    re.IGNORECASE,
)

# Trailing politeness words that don't change the meaning.
_TRAILING_POLITENESS_RE = re.compile(
    r"\s+(?:please|kindly|for\s+me|now|asap|at\s+once)\s*[.?!]?\s*$",
    re.IGNORECASE,
)


def _strip_politeness(text: str) -> str:
    """Return ``text`` with leading and trailing politeness
    markers removed. The result is normalised for downstream
    regex matching without changing the user's meaning.

    Also collapses simple verb paraphrases (see/show/view X
    folder → open X folder, take me to X → open X) so the
    existing folder/file patterns match without enumerating
    every natural-language variant.
    """
    if not text:
        return text
    stripped = _POLITENESS_PREFIX_RE.sub("", text.strip(), count=1)
    stripped = _TRAILING_POLITENESS_RE.sub("", stripped)

    # "see/show/view my X folder" / "show me my X" -> "open my X"
    #
    # IMPORTANT: "show me the desktop" / "show desktop" /
    # "show me my desktop" are the Windows "minimize all"
    # gesture (window.show_desktop), NOT a folder-open
    # request, even though "my desktop" reads as if the
    # user is asking about a folder. The bare noun
    # "desktop" is ambiguous: it can mean the visible
    # surface (the gesture) OR the Desktop folder. The
    # gesture is the default because:
    #   * "show desktop" is the canonical Windows shortcut
    #     for "minimize everything"
    #   * when the user says "show me my desktop" they
    #     almost always mean "minimize all my windows so
    #     I can see my desktop" (the surface), not "open
    #     the Desktop folder"
    # The Desktop folder is reachable via "open the
    # desktop folder" / "navigate to my desktop" (the
    # "folder" disambiguator forces the folder.open
    # path).
    def _show_to_open(text: str) -> str:
        m = re.match(
            r"^(?:see|show|view|display|take\s+a\s+look\s+at)\s+(?:me\s+)?"
            r"(?P<noun>.+?)$",
            text,
            flags=re.IGNORECASE,
        )
        if not m:
            return None  # type: ignore[return-value]
        noun = m.group("noun").strip()
        lowered_noun = noun.lower()
        # Desktop gesture short-circuit: "show me the
        # desktop" / "show me my desktop" / "show desktop"
        # / "see my desktop" all map to window.show_desktop.
        if re.search(r"\bdesktop\b", lowered_noun):
            return "show " + noun
        return "open " + noun

    _show_substituted = _show_to_open(stripped)
    if _show_substituted is not None:
        stripped = _show_substituted

    # "show me my X" / "show me the X" -> "open my X" / "open the X"
    stripped = re.sub(
        r"^open\s+me\s+(my|the)\s+",
        r"open \1 ",
        stripped,
        count=1,
        flags=re.IGNORECASE,
    )
    # "show me the desktop" / "i want to see my desktop" ->
    # "show desktop" so the existing window.show_desktop
    # pattern matches. Without this guard the verb-paraphrase
    # substitution above converts "show me the desktop" to
    # "open the desktop" which routes to folder.open
    # (desktop folder) instead of window.show_desktop.
    if re.fullmatch(r"show\s+(?:my|the)\s+desktop", stripped, re.IGNORECASE):
        stripped = "show desktop"

    # "take me to X" / "head over to X" -> "go to X"
    stripped = re.sub(
        r"^(?:take\s+me\s+to|head\s+over\s+to|bring\s+me\s+to)\s+",
        "go to ",
        stripped,
        count=1,
        flags=re.IGNORECASE,
    )

    return stripped.strip()


# =========================================================
# WORKFLOW DECISION ENGINE
# =========================================================

class WorkflowDecisionEngine:
    """
    Central decision layer for Genesis.

    Routing hierarchy:

        Level 3
            AI Operating System

        Level 2
            Multi-Agent
            Single-Agent

        Level 1
            Conversation

    This class determines intent only.

    It does NOT execute operating-system operations.
    """

    VERSION = "3.2"

    # =====================================================
    # INITIALIZATION
    # =====================================================

    def __init__(
        self,
        registry=None,
        context=None,
        conversation=None,
        memory=None,
        ai_engine=None,
        capability_resolver=None,
    ):
        self.registry = registry
        self.context = context
        self.conversation = conversation
        self.memory = memory

        # -------------------------------------------------
        # CAPABILITY CONTROL PLANE — ALWAYS PRESENT
        # -------------------------------------------------
        # The control plane must not be opt-in. A decision engine
        # constructed without an explicit resolver previously ran
        # with NO capability verification at all, which made
        # routing behave identically with the resolver on or off.
        # Default to a real CapabilityResolver so every production
        # path routes through the same resolution contract.
        if capability_resolver is None:
            try:
                from genesis_os.capability_resolver import (
                    CapabilityResolver,
                )
                capability_resolver = CapabilityResolver()
            except Exception:
                capability_resolver = None
        self.capability_resolver = capability_resolver

        # -------------------------------------------------
        # LLM-BASED SEMANTIC INTENT RESOLUTION
        # -------------------------------------------------
        # Initialize the LLM intent resolver for handling
        # novel phrasings that don't match deterministic patterns.
        if ai_engine is not None:
            try:
                from genesis_os.llm_intent_resolver import LLMIntentResolver
                self._llm_resolver = LLMIntentResolver(
                    ai_engine=ai_engine,
                    decision_engine=self,
                )
            except Exception:
                self._llm_resolver = None
        else:
            self._llm_resolver = None

        # -------------------------------------------------
        # DETERMINISTIC UNSEEN-TASK SEMANTIC CLASSIFIER
        # -------------------------------------------------
        # Architectural fix for unseen-task generalisation.
        # This runs BEFORE the LLM fallback so novel phrasings
        # (anaphoric file ops, window idioms, math NL, archive
        # requests) are recognised deterministically instead of
        # silently dropping to Level 1 conversation.
        try:
            from agents.unseen_task_semantic import (
                UnseenTaskSemanticClassifier,
            )
            self._unseen_task_classifier = (
                UnseenTaskSemanticClassifier()
            )
        except Exception:
            self._unseen_task_classifier = None

    # =====================================================
    # MAIN DECISION
    # =====================================================

    def decide(
        self,
        text: str,
        prior_turn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Decide the appropriate Genesis workflow.

        Priority:

            1. Level 3 OS (including compound L3 requests)
            2. Level 2 Multi-Agent
            3. Level 2 Single-Agent
            4. Level 1 Conversation

        ITEM 4 -- ``prior_turn`` is the minimal context channel. It is
        the single preceding user turn, supplied by the caller, and it
        is threaded ONLY into the semantic/grounding path so that an
        elided reference ("that", "it", "this one") can be resolved
        against it.

        SCOPE, deliberately narrow:

          * It does NOT touch the deterministic/regex layer. That layer
            has no mechanism for this and must not grow one; the
            "keywords/regex as fast hints" contract is unchanged.
          * It is NOT conversation history, NOT session state, NOT
            memory. One string, one request, no chain.
          * Default is ``None``, and when it is ``None`` every code
            path below behaves exactly as it did before the parameter
            existed. That is the no-op guarantee, pinned by tests in
            ``test_phase3_minimal_context_channel.py``.
        """

        # Preserve the user's original casing so extracted
        # targets (folder names, file names, search queries)
        # keep their natural form.
        self._last_case_form = (
            self._preserve_case_text(text)
        )

        text = self._normalize_text(text)

        # -------------------------------------------------
        # EMPTY REQUEST
        # -------------------------------------------------

        if not text:
            return self._decision(
                level=1,
                mode="conversation",
                task="",
                reason="Empty request.",
                confidence=1.0,
            )

        # =================================================
        # COMPOUND L3 PRE-CHECK
        # =================================================
        # A request with multiple L3-actionable clauses
        # joined by "and" / "then" / "," must route to L3
        # regardless of whether the LAST clause resolves to
        # a clear intent. Without this pre-check the engine
        # collapses compound L3 requests to the LAST
        # detected operation, drops all preceding clauses,
        # and (when the last clause is ambiguous) falls to
        # L1 conversation — a silent loss of capability.
        #
        # Examples that were broken before this gate:
        #   * "open my downloads and find the latest PDF"
        #   * "open my downloads and open the latest PDF"
        #   * "open Word and open my essay.docx"
        # All three are L3 compound OS requests; they must
        # route to L3 so the compound router / workflow
        # engine can decompose them. The pre-check is
        # conservative: it only fires when at least one
        # clause already resolves to a CONFIDENT L3 intent.
        compound_signal = self._detect_compound_l3_signal(text)
        if compound_signal is not None:
            # Pass the original full text to OS intent
            # detection so the workflow engine sees the
            # whole request. The compound router handles
            # the decomposition.
            os_decision = self._detect_os_intent(text)
            if os_decision is None:
                for fragment in re.split(
                    r"\s+(?:and|then|after\s+that|next|plus)\s+",
                    text,
                    flags=re.IGNORECASE,
                ):
                    candidate = self._detect_os_intent(fragment.strip())
                    if candidate is not None:
                        os_decision = candidate
                        break
            os_decision = self._resolve_with_capability_control_plane(
                os_decision
            )
            if os_decision is not None:
                return self._decision(
                    level=3,
                    mode="os",
                    task=text,
                    intent=os_decision.get(
                        "intent", "compound.os"
                    ),
                    application=os_decision.get("application"),
                    target=os_decision.get("target"),
                    parameters={
                        **os_decision.get("parameters", {}),
                        "is_compound": True,
                        "compound_clause_count": (
                            compound_signal
                        ),
                    },
                    reason=(
                        "Compound L3 request: "
                        f"{compound_signal} L3 clause(s) "
                        "joined by a conjunction. The compound "
                        "router / workflow engine decomposes "
                        "this into independent steps."
                    ),
                    confidence=max(
                        os_decision.get("confidence", 0.0),
                        0.92,
                    ),
                )

        # =================================================
        # LEVEL 3 — AI OPERATING SYSTEM
        # =================================================

        os_decision = self._detect_os_intent(text)
        os_decision = self._resolve_with_capability_control_plane(
            os_decision
        )

        # =================================================
        # ITEM 20 — CONTEXT-AWARE GROUNDING WHEN THE
        # DETERMINISTIC LAYER PRODUCED NOTHING
        # =================================================
        # The ledger recorded this as "the semantic path was skipped
        # when there is no deterministic candidate". That is not what
        # the code does: _detect_extended_os_intent already falls back
        # to _try_semantic_intent_resolution(text) when nothing
        # deterministic matched. Grounding therefore DID run.
        #
        # The real defect is narrower and matches the measured symptom
        # exactly (shortlist(prior=False) on cases where a prior turn
        # existed): that internal fallback has no way to receive
        # prior_turn, so grounding ran blind to conversational context.
        #
        # The fix deliberately does NOT add a context parameter to the
        # deterministic layer. test_phase3_minimal_context_channel.py
        # pins that boundary on purpose — "the regex layer ... has no
        # mechanism for this and must not grow one: keywords/regex as
        # fast hints depends on it staying context-free." Threading
        # prior_turn into _detect_os_intent was tried and reverted
        # precisely because it broke that invariant.
        #
        # So the prior turn is applied from here, in the layer that is
        # allowed to hold conversational state, and only when one was
        # actually supplied. Cost is therefore bounded to the case the
        # fix exists for: an anaphoric request that the deterministic
        # layer could not classify AND that carries a prior turn. A
        # decisive match still costs zero semantic calls, and a
        # no-candidate request with no prior turn still costs exactly
        # the one call the internal fallback already made.
        if prior_turn and not isinstance(os_decision, dict):
            contextual = self._try_semantic_intent_resolution(
                text, prior_turn=prior_turn
            )
            if contextual is not None:
                os_decision = contextual

        # =================================================
        # ROADMAP TASK 4 — KEYWORDS/REGEX ARE FAST HINTS
        # =================================================
        # The deterministic layer is allowed to answer instantly,
        # but only when its match is anchored AND its own family
        # does not contradict it. A targetless match inside a
        # multi-member capability family, where a sibling describes
        # the request strictly better, is a HINT: one keyword hit
        # cannot arbitrate between siblings that share a domain
        # (media.next / media.previous / media.play_pause /
        # media.stop). Before this rule the hint was promoted
        # unconditionally, so the semantic layer was never asked and
        # a family-level guess could not be corrected by a model
        # that would have got it right.
        #
        # The contradiction test matters. Treating EVERY unanchored
        # match as a hint is unsafe: it let the model overwrite a
        # correct deterministic answer ("write hello world":
        # gui.type_text -> document.create_txt).
        #
        # Concrete targets (a named application, file or path) are
        # left alone: those matches are anchored, cheap, and correct.
        # ITEM 20: the no-candidate path is handled inside
        # _detect_os_intent, which already falls back to the semantic
        # resolver when nothing deterministic matched (line ~3182).
        # That fallback was the real defect: it called
        # _try_semantic_intent_resolution(text) with NO prior_turn, so
        # grounding ran but could never use conversational context,
        # which is exactly the measured shortlist(prior=False) symptom.
        # prior_turn is now forwarded into that call (and into the
        # guarded-text fallback), which is a smaller and cheaper fix
        # than opening this block for no-candidate requests: doing it
        # here would have cost a SECOND semantic call per anaphoric
        # request, because _detect_os_intent has already made the first.
        #
        # _deterministic_match_is_only_a_hint() returning False for a
        # None decision is therefore still correct here: this block is
        # about ARBITRATING two candidates, and with no candidate there
        # is nothing to arbitrate. Grounding already happened upstream.
        if self._deterministic_match_is_only_a_hint(
            os_decision, text
        ):
            hinted = os_decision
            # ITEM 4: forwarded only when supplied, so the no-prior
            # call is literally the pre-Item-4 call.
            semantic = self._try_semantic_intent_resolution(
                text,
                **({"prior_turn": prior_turn} if prior_turn else {}),
            )
            if semantic is not None:
                os_decision = semantic
            else:
                # The semantic layer could not do better; keep the
                # hint rather than losing a valid decision.
                os_decision = hinted

        # =================================================
        # CROSS-DOMAIN CAPABILITY ARBITRATION
        # =================================================
        # The hint above only compares siblings INSIDE the matched
        # capability's own domain, so it is structurally blind to a
        # cross-domain mistake. Measured on fresh paraphrases: a
        # deterministic candidate in one domain was returned while
        # the correct capability lived in another, and no hook could
        # see it. This is the narrowest boundary that fixes it: it
        # sits after the deterministic candidate and its control
        # plane evidence exist, and before the promotion gate that
        # would otherwise return.
        #
        # Arbitration is capability-first. Both candidates are named
        # registered capabilities, so no domain is privileged and the
        # comparison cannot be family-scoped by construction.
        os_decision = self._arbitrate_os_decision(
            text, os_decision, prior_turn=prior_turn
        )
        if os_decision is not None:

            confidence = os_decision.get(
                "confidence",
                0.0,
            )

            parameters = os_decision.get(
                "parameters",
                {},
            )

            has_application = bool(
                os_decision.get("application")
            )

            has_target = bool(
                os_decision.get("target")
            )

            requires_target = bool(
                parameters.get("requires_target")
            )

            # Promote strong, concrete OS decisions. A resolved
            # target is sufficient even when the capability is not
            # an application (files, settings, browser, Wi-Fi).
            # Long-term memory operations also qualify: "remember
            # that X" is a Level 1 decision but the L1 path needs
            # the OS detection layer's memory.store intent to
            # reach the LongTermMemory component.
            is_memory_op = os_decision.get("intent") == "memory.store"
            # An anaphoric document reference (this PDF /
            # this document) returns an empty target with
            # `anaphoric_target=True`. The runtime entity
            # binder resolves the target before dispatch; the
            # decision itself is structurally valid and
            # reaches the right intent, so it should be
            # promoted rather than dropped to L1.
            is_anaphoric_doc = bool(
                parameters.get("anaphoric_target")
            )
            # GUI typing/pasting resolves through the
            # `gui.type_text` / `gui.paste_text` intent.
            # These decisions intentionally carry
            # `target=None` when the user did not name a
            # window ("type Hello from Genesis") so the
            # executor types into whichever window
            # currently has focus. The decision is
            # structurally valid when the resolved
            # intent has a `text` payload, so accept it on
            # the same footing as anaphoric references.
            gui_text_intent = os_decision.get("intent") in (
                "gui.type_text", "gui.paste_text",
            )
            has_gui_text = gui_text_intent and bool(
                parameters.get("text")
            )
            semantic_resolved = bool(
                parameters.get("_semantic_resolution")
            ) and bool(
                parameters.get("_capability_resolution")
            )
            # ITEM 20C (R9): a MODEL-proposed OS decision must not
            # outrank the L2 ownership check. The gate below used to
            # return before the conversational guard and the L2 agent
            # detectors ran, so the LLM's proposal for phrasings the
            # deterministic engine classifies as Level 2 work
            # ("Research the latest AI safety papers.", "Study biology
            # with me.", "Analyze this spreadsheet for outliers.")
            # came back Level 3 by construction -- while the very same
            # engine with the resolver disabled routed all three to
            # the correct L2 agents. Declining the promotion is
            # narrow by design: it fires only for semantic-origin
            # decisions whose text the deterministic L2 detectors
            # claim, so deterministic promotions (no model marker)
            # and semantic proposals for unowned text are untouched.
            l2_owns_text = (
                semantic_resolved
                and bool(self._detect_multi_agents(text))
            )
            if (
                (
                    confidence >= 0.90
                    or (
                        semantic_resolved
                        and confidence >= 0.80
                    )
                )
                and (
                    has_application
                    or has_target
                    or requires_target
                    or is_memory_op
                    or is_anaphoric_doc
                    or has_gui_text
                    or semantic_resolved
                )
                and not l2_owns_text
            ):
                return os_decision

        # =================================================
        # CONVERSATIONAL GUARD
        # =================================================
        # Without this guard, the agent keyword detector
        # below would misclassify educational/conversational
        # requests ("Define machine learning", "Explain
        # quantum mechanics", "Tell me about biology") as
        # Study Agent / Research Agent work because their
        # keyword maps match domain words ("machine",
        # "learning", "biology"). Such requests are L1
        # conversation. The guard is intentionally placed
        # AFTER the L3 OS pre-check (so genuine L3 OS
        # requests are not blocked) and AFTER the
        # conversational pre-screen above, but BEFORE
        # the agent detector.
        # The guard is suppressed when the text contains a
        # strong agent keyword (outliers, correlations,
        # variance, etc.). A user asking "what are the
        # outliers in this data" is a data-analysis task,
        # not a general knowledge question.
        _AGENT_KEYWORD_PROBES = (
            # Data
            "outliers", "correlations", "variance",
            "covariance", "mean and standard deviation",
            "analyze this", "analyze the", "analyse this",
            "analyse the", "analyze my", "analyse my",
            "this dataset", "this spreadsheet", "this csv",
            "this data", "in this data",
            "compare these", "compare the two", "compare my",
            "the correlation", "the variance", "the outliers",
            "the trend", "the mean", "the median",
            # Research
            "research papers", "academic papers", "look up",
            "look for papers", "literature review",
            "scientific literature", "state of the art",
            "state-of-the-art", "look up recent",
            "look for recent", "recent papers", "recent paper",
            "papers on", "research on", "research about",
            "current state", "current state of",
            "the state of", "state of fusion",
            "papers about", "papers for",
            # Coding
            "write a function", "write a class", "write a method",
            "write a script", "write code", "write a program",
            "write the code", "implement a",
        )
        if self._is_conversational_or_educational(text):
            lowered = text.lower()
            if not any(probe in lowered for probe in _AGENT_KEYWORD_PROBES):
                return self._decision(
                    level=1,
                    mode="conversation",
                    task=text,
                    reason=(
                        "The request is a conversational or "
                        "educational prompt that does not "
                        "require a specialized agent."
                    ),
                    confidence=0.85,
                )

        # =================================================
        # LEVEL 2 — MULTI AGENT
        # =================================================

        multi_agents = self._detect_multi_agents(
            text
        )

        if len(multi_agents) >= 2:
            return self._decision(
                level=2,
                mode="multi_agent",
                agents=multi_agents,
                task=text,
                reason=(
                    "Multiple specialized capabilities "
                    "are required."
                ),
                confidence=0.90,
            )

        # =================================================
        # LEVEL 2 — SINGLE AGENT
        # =================================================

        single_agent = self._detect_single_agent(
            text
        )

        if single_agent:
            return self._decision(
                level=2,
                mode="single_agent",
                agent=single_agent,
                agents=[single_agent],
                task=text,
                reason=(
                    "A specialized agent is best suited "
                    "for this request."
                ),
                confidence=0.88,
            )

        # =================================================
        # LEVEL 3 — SEMANTIC GROUNDING FOR AMBIGUOUS TEXT
        # =================================================
        # Everything above this point is lexical: regex layers and
        # their confidence thresholds. A request whose wording
        # carries no lexical trigger never reaches them, and would
        # fall straight to Level 1 conversation.
        #
        # MEASURED: the lexical probes cannot tell such a request
        # from ordinary conversation. On synthetic input these two
        # agree on every probe (domain evidence, specific action
        # verb, state hint, small talk all False for both):
        #
        #   "i need this written out somewhere durable"  a real
        #                                                   document.create request
        #   "that genuinely cheered me up"               conversation
        #
        # So the decision is escalated to semantic evidence. The
        # model must commit to actionable, name a registered
        # capability, and quote a verbatim span that justifies it;
        # the span is verified against the request, and the result
        # is re-validated by the existing control plane and safety
        # layer. Conversation ends at None and stays Level 1.
        grounded = self._grounded_os_decision(text, prior_turn)
        if grounded is not None:
            return grounded

        # =================================================
        # LEVEL 1 — CONVERSATION
        # =================================================

        return self._decision(
            level=1,
            mode="conversation",
            task=text,
            reason=(
                "The request is best handled by "
                "Genesis core intelligence."
            ),
            confidence=0.85,
        )

    # =====================================================
    # DECISION OBJECT
    # =====================================================

    def _decision(
        self,
        level: int,
        mode: str,
        task: str,
        reason: str,
        confidence: float = 0.80,
        agent: Optional[str] = None,
        agents: Optional[List[str]] = None,
        intent: Optional[str] = None,
        application: Optional[str] = None,
        target: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a standardized Genesis workflow decision.
        """

        return {
            "level": level,
            "mode": mode,
            "task": task,

            "agent": agent,
            "agents": agents or [],

            "intent": intent,

            "application": application,
            "target": target,

            "parameters": parameters or {},

            "confidence": confidence,
            "reason": reason,

            "engine_version": self.VERSION,
        }

    # =====================================================
    # NORMALIZATION
    # =====================================================

    def _detect_compound_l3_signal(self, text: str) -> Optional[int]:
        """Return the number of L3-actionable clauses in
        ``text`` when the text is genuinely compound
        (multiple clauses joined by " and " / " then " /
        ",") and at least one clause is L3-actionable.

        Used as a pre-check in ``decide()`` to ensure
        compound L3 requests route to L3 even when the
        LAST clause would otherwise drop the request to L1
        (e.g. an anaphoric 2nd clause that the single-
        clause pipeline cannot resolve).

        Conservative: returns None for non-compound text,
        text that is a single L3 step, or compound text
        where none of the clauses are L3-actionable.
        """
        if not text:
            return None
        # Reject conversational opens
        if re.match(
            r"^\s*(?:is\s+(?:this|that|my)|"
            r"how\s+(?:do|can|would|should|much|many)|"
            r"what(?:\s+is|\s+are|\s+does|\s+do)|"
            r"why|when|where|who|define|explain|"
            r"tell\s+me|write\s+(?:a|an|the|me)|"
            r"help\s+me)\b",
            text,
        ):
            return None
        # Split on " and " / " then " / "," between L3 verbs.
        # Use the same verb set the splitter uses.
        _L3_VERB_SPLIT = re.compile(
            r"\s+(?:and|then|after\s+that|next|and\s+then|plus|"
            r",\s*then)\s+(?="
            r"(?:open|launch|start|close|fire\s+up|spin\s+up|"
            r"boot\s+up|find|search|look\s+up|locate|show\s+me|"
            r"go\s+to|navigate\s+to|visit|read|write|create|"
            r"make|edit|copy|move|rename|delete|remove|send|"
            r"share|save|open\s+the|click|select|type|paste|"
            r"minimize|restore|minimise|press|uninstall|install|"
            r"download|upload|unzip|zip|extract|sort|filter|"
            r"rank|calculate|compute|play|pause|stop|skip|"
            r"next|previous|mute|unmute|set|turn|switch|"
            r"enable|disable|activate|deactivate|toggle|"
            r"check|verify|inspect|list|show|view|display|"
            r"empty|clear|lock|unlock|translate|send|forward|"
            r"reply|attach|pin|unpin|minimize|close|quit|exit|"
            r"capture|summarize|highlight|mark|delete)\b"
            r")",
            re.IGNORECASE,
        )
        parts = _L3_VERB_SPLIT.split(text)
        if len(parts) < 2:
            return None
        # Reject splits that don't make sense (e.g. "research
        # and development" — "and" inside a noun phrase).
        # Each part must be at least 3 chars.
        parts = [p.strip() for p in parts if len(p.strip()) >= 3]
        if len(parts) < 2:
            return None
        # Reject if any part is conversational ("please",
        # "hello", "what is", etc.)
        conversational_prefix = re.compile(
            r"^\s*(?:please|hi|hello|hey|good\s+morning|"
            r"i\s+was\s+wondering|do\s+you|can\s+you|"
            r"could\s+you|would\s+you|would\s+it\s+be)\b",
            re.IGNORECASE,
        )
        l3_resolvable_count = 0
        for part in parts:
            if conversational_prefix.match(part):
                return None
            # Probe whether this clause is L3-actionable.
            if self._is_l3_actionable(part):
                l3_resolvable_count += 1
        if l3_resolvable_count >= 1 and len(parts) >= 2:
            return len(parts)
        return None

    @staticmethod
    def _is_l3_actionable(fragment: str) -> bool:
        """Cheap probe: does ``fragment`` look like an
        L3-actionable clause? This is NOT a full decision;
        it only asks "would the workflow engine be able to
        dispatch this clause to a Level-3 OS capability?".
        Used by the compound L3 pre-check.
        """
        if not fragment:
            return False
        f = fragment.lower().strip()
        if not f:
            return False
        # Common L3 verbs / phrases.
        l3_patterns = (
            r"\bopen\s+(?:the\s+|my\s+)?(?:chrome|firefox|edge|"
            r"word|excel|powerpoint|outlook|notepad|vs\s*code|"
            r"calculator|paint|settings|file\s+explorer|"
            r"terminal|command\s+prompt|powershell|"
            r"downloads|documents?|desktop|pictures|music|"
            r"videos?|projects?|workspace|reports?|invoices?|"
            r"slack|teams|photos|maps|store|onedrive|clock|"
            r"weather|microsoft\s+\w+|app)\b",
            r"\bfind\s+(?:the\s+|my\s+)?(?:latest|newest|"
            r"most\s+recent|file|document|spreadsheet|pdf)\b",
            r"\bsearch\s+(?:for\s+)?(?:the\s+)?(?:latest|"
            r"newest|file|document|spreadsheet|pdf|notes?)\b",
            r"\bclose\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\blaunch\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bstart\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bgo\s+to\s+(?:my\s+|the\s+)?(?:\w+)",
            r"\bnavigate\s+to\s+(?:my\s+|the\s+)?(?:\w+)",
            r"\bopen\s+(?:my\s+|the\s+)?(?:\w+)",
            r"\bshow\s+me\s+(?:my\s+|the\s+)?(?:\w+)",
            r"\bread\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bwrite\s+(?:a\s+)?(?:new\s+)?(?:\w+)",
            r"\bcreate\s+(?:a\s+)?(?:new\s+)?(?:\w+)",
            r"\bcopy\s+(?:it\s+|the\s+|\w+\s+)?to\s+",
            r"\bmove\s+(?:it\s+|the\s+|\w+\s+)?to\s+",
            r"\bdelete\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bremove\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bsave\s+(?:it\s+|the\s+|\w+\s+)?(?:to|as)\s+",
            r"\bunzip\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bextract\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bzip\s+(?:up\s+)?(?:the\s+|my\s+)?(?:\w+)",
            r"\brename\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bsort\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bfilter\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\brank\s+(?:the\s+|my\s+)?(?:\w+)",
            r"\bcalculate\s+(?:the\s+)?(?:\w+)",
            r"\bsum\s+(?:the\s+)?(?:\w+)",
            r"\bplay\s+(?:the\s+)?(?:\w+)",
            r"\bpause\s+(?:the\s+)?(?:\w+)",
            r"\btype\s+(?:['\"])?(?:\w+)",
            r"\bclick\s+(?:on\s+)?(?:the\s+)?(?:\w+)",
        )
        for pat in l3_patterns:
            if re.search(pat, f):
                return True
        return False

    @staticmethod
    def _normalize_text(
        text: Any,
    ) -> str:
        """
        Normalize user input into canonical form for intent detection.

        Examples:
            Open Chrome.
            PLEASE OPEN CHROME!
            Could you launch Chrome for me?
        """
        if text is None:
            return ""

        s = str(text).strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()

        s = " ".join(s.split()).lower()

        # Normalize common English contractions so
        # conversational prefix detection ("what is",
        # "what are", "where is", ...) is consistent
        # whether the user writes "what is" or "what's".
        # Without this normalization, the conversational
        # guard would miss "what's the difference between
        # X and Y" (routed to L2 Research Agent) but
        # catch "what is the difference" (routed to L1).
        s = re.sub(r"\bwhat's\b", "what is", s)
        s = re.sub(r"\bwhere's\b", "where is", s)
        s = re.sub(r"\bthat's\b", "that is", s)
        s = re.sub(r"\blet's\b", "let us", s)

        # Strip trailing polite punctuation like '.', '!', ',', ';', ':', '?'
        while s and s[-1] in {".", "!", ",", ";", ":", "?"}:
            if len(s) > 1 and s[-2].isalnum():
                last_word = s.split()[-1]
                if last_word.count(".") > 1 or not any(
                    last_word.endswith(ext + s[-1])
                    for ext in (
                        ".txt", ".csv", ".docx", ".pdf", ".py", ".xlsx",
                        ".json", ".xml", ".yaml", ".yml", ".md", ".png",
                        ".jpg", ".zip", ".exe"
                    )
                ):
                    s = s[:-1].strip()
                else:
                    break
            else:
                s = s[:-1].strip()

        return s

    def _preserve_case_text(self, text: Any) -> str:
        """
        Return the normalized form of the input WITHOUT
        lowercasing, using exactly the same punctuation and
        whitespace rules as _normalize_text.

        This lets target extraction keep natural casing
        ("Genesis Test" stays "Genesis Test").
        """
        if text is None:
            return ""

        s = str(text).strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()

        s = " ".join(s.split())

        while s and s[-1] in {".", "!", ",", ";", ":"}:
            if len(s) > 1 and s[-2].isalnum():
                last_word = s.split()[-1]
                if last_word.count(".") > 1 or not any(
                    last_word.endswith(ext + s[-1])
                    for ext in (
                        ".txt", ".csv", ".docx", ".pdf", ".py", ".xlsx",
                        ".json", ".xml", ".yaml", ".yml", ".md", ".png",
                        ".jpg", ".zip", ".exe"
                    )
                ):
                    s = s[:-1].strip()
                else:
                    break
            else:
                s = s[:-1].strip()

        return s

    @staticmethod
    def _is_conversational_or_educational(text: str) -> bool:
        """
        Identify requests that are purely conversational, academic,
        educational, or linguistic even if they mention OS terms.

        Examples:
            "Is this IELTS sentence correct?"
            "How do I improve my essay?"
            "What does running mean?"
            "Write a sentence about Chrome."
            "Explain what Windows is."
            "Explain what a computer is."
            "What is an operating system?"
        """
        t = text.lower().strip()

        conversational_prefixes = (
            "is this ",
            "is that ",
            "is my ",
            "how do i ",
            "how can i ",
            "how to ",
            "what does ",
            "what is ",        # "what is biology" / "what is the
                                  # difference between X and Y"
            "what is an ",
            "what is a ",
            "what is the ",
            "what are ",
            "why does ",
            "why is ",
            "explain what ",
            "explain how ",
            "explain why ",
            "explain the ",
            "tell me about ",
            "tell me what ",
            "write a sentence ",
            "write an essay ",
            "write a paragraph ",
            "write a poem ",
            "write a story ",
            "define ",
            "meaning of ",
        )

        for prefix in conversational_prefixes:
            if t.startswith(prefix):
                # Exception: "what is <math>" / "what is 9 * 9"
                # is a math query, not a conversational
                # question. The body of "what is" is a number
                # or arithmetic expression.
                if t.startswith("what is "):
                    body = t[len("what is "):].strip()
                    if re.match(
                        r"^[\d\s\.\+\-\*/%\(\)]+",
                        body,
                    ) or re.match(
                        r"^[\d]+\s*(?:%|percent|x|times|"
                        r"divided\s+by|plus|minus)\s+",
                        body,
                    ):
                        return False
                # Exception: "what are my X" / "show my X" /
                # "what is my X" / "list my X" are OS-level
                # personal-asset queries, not general
                # knowledge questions. The possessive "my"
                # signals the user is asking about THEIR
                # own state, not asking for a definition.
                if t.startswith(("what are my ", "what is my ",
                                 "show my ", "show me my ",
                                 "list my ", "find my ",
                                 "where are my ", "where is my ",
                                 "open my ", "delete my ")):
                    return False
                # Exception: "what's in the clipboard" /
                # "what is in the clipboard" — the clipboard
                # is a real OS object the user is asking
                # about, not a general knowledge question.
                if t.startswith(("what's in ", "what is in ",
                                 "what's on my ", "what is on my ",
                                 "what's on the ", "what is on the ")):
                    if "clipboard" in t:
                        return False
                # Exception: genuine application status checks
                if t.startswith(("is ", "what's ", "what is ")):
                    if re.search(r"\b(running|open|active|closed|installed)\b\??$", t):
                        return False
                return True

        # General knowledge / reasoning questions that are
        # NEVER OS-level even when they mention OS-adjacent
        # words (biology, history, geography, logic, etc.).
        if t.startswith(
            (
                "if all ", "if every ", "if some ",
                "can we conclude", "can we infer",
                "how does ", "how do ", "how did ", "how can ",
                "where is ", "where are ", "where do ",
                "when did ", "when was ", "when is ",
                "who is ", "who was ", "who are ",
                "where does ", "when does ",
            )
        ):
            return True

        if any(term in t for term in (
            "sentence correct",
            "grammar correct",
            "ielts sentence",
            "improve my essay",
            "mean in english",
            "definition of",
        )) and not any(t.startswith(p) for p in ("find ", "search ", "open ", "locate ", "show ")):
            return True

        return False

    @staticmethod
    def _is_folder_anchor(text: str) -> bool:
        """Return True when ``text`` names a canonical Windows user
        folder (downloads, documents, desktop, ...) and is
        therefore a folder.open request rather than an
        application.open request.

        Used by the application-target priority gate so that
        "open my downloads" still routes to ``folder.open``
        (downloads is a folder, not an app) while "open
        File Explorer" routes to ``application.open``
        (File Explorer is the app, downloads would be inside it).
        """
        lowered = text.lower()
        # Standard user folders are always folder targets even
        # when the alias dictionary happens to also know them
        # as an app (e.g. "pictures" is a folder, not an app).
        folder_nouns = {
            "downloads", "download", "documents", "document",
            "docs", "desktop", "pictures", "photos", "music",
            "videos", "projects", "project", "workspace",
            "reports", "invoices", "archive", "backups",
            "home", "root", "scratch", "temp", "recycle bin",
        }
        # Match "open my downloads" / "open the documents
        # folder" / "show me the desktop" etc.
        for noun in folder_nouns:
            if re.search(
                r"\b" + re.escape(noun) + r"\b",
                lowered,
            ):
                # Make sure the noun is the FOLDER target and
                # not e.g. "downloads of the music folder".
                # "open my downloads" -> yes folder
                # "open Pictures and Music" -> yes folder
                # "open Pictures and start a slide show" ->
                # yes folder (Pictures is a folder, the verb
                # in this engine is unified)
                return True
        return False

    # =====================================================
    # LEVEL 3
    # OS INTENT DETECTION
    # =====================================================

    def _detect_os_intent(
        self,
        text: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect Level 3 operating-system requests.

        Current Level 3 capabilities:
            application (open, close, inspect, list)
            filesystem (search, read, inspect, delete, open, move, copy, create)
            folder (open, create, inspect, organize, rename, move, delete)
            process (list, inspect)
            browser (open_url, search)
            system (open_settings, status)
            network (list_wifi, connect_wifi)

        This method NEVER executes the operation.
        """

        text = self._normalize_text(text)

        if not text:
            return None

        # -------------------------------------------------
        # POLITENESS STRIPPING
        # -------------------------------------------------
        # Strip leading "please", "could you", "I'd like to",
        # etc. so the patterns below match the user's actual
        # intent ("open chrome" rather than "could you open
        # chrome please"). The original text is preserved on
        # ``self._last_case_form`` for case-preserving target
        # extraction downstream.
        text = _strip_politeness(text)
        if not text:
            return None

        # -------------------------------------------------
        # CONVERSATIONAL GUARD
        # -------------------------------------------------
        # This guard keeps educational/conversational text away
        # from the REGEX layer below. It must not also block the
        # semantic resolver: "what is playing right now" starts
        # with "what is " and was being dropped here even though
        # the LLM resolves it correctly. The semantic path applies
        # its own gate (looks_actionable), which passes capability
        # questions and blocks knowledge questions.
        if self._is_conversational_or_educational(text):
            semantic = self._semantic_fallback_for_guarded_text(
                text
            )
            if semantic is not None:
                return semantic
            return None

        if _SAVE_AS_PDF_RE.match(text):
            return self._decision(
                level=3,
                mode="os",
                task=text,
                reason="Create a PDF from the preceding task output.",
                confidence=0.96,
                intent="document.create_pdf",
                target="research.pdf",
                parameters={
                    "output": "research.pdf",
                    "content_source": "agent_result",
                    "requires_agent_output": True,
                },
            )

        # -------------------------------------------------
        # DETERMINISTIC UNSEEN-TASK SEMANTIC CLASSIFIER
        # -------------------------------------------------
        # Catches whole families of unseen phrasings that the
        # regex patterns below do not enumerate: anaphoric file
        # ops ("the file I just edited"), window idioms ("shut
        # everything down"), natural-language math, archive
        # intents. Runs BEFORE the extended pipeline so the
        # regex patterns still act as the source of truth for
        # the well-known phrasings.
        classifier = getattr(
            self, "_unseen_task_classifier", None
        )
        if classifier is not None:
            try:
                semantic = classifier.classify(text)
            except Exception:
                semantic = None
            if semantic is not None:
                return self._decision(
                    level=3,
                    mode="os",
                    task=text,
                    intent=semantic.intent,
                    target=semantic.target or None,
                    confidence=semantic.confidence,
                    parameters=semantic.parameters,
                    reason=(
                        f"Unseen-task semantic classifier "
                        f"(family={semantic.family}): "
                        f"{semantic.description}"
                    ),
                )

        # -------------------------------------------------
        # EXPANDED LEVEL 3 INTENTS
        # -------------------------------------------------
        expanded = self._detect_extended_os_intent(text)
        if expanded is not None:
            return expanded

        # -------------------------------------------------
        # SAFETY: SYSTEM SHUTDOWN
        # -------------------------------------------------

        if self._contains_system_shutdown(text):
            return None

        # -------------------------------------------------
        # DETECT ACTION
        # -------------------------------------------------

        action = self._detect_application_action(text)

        if action is None:
            return None

        # -------------------------------------------------
        # RESOLVE APPLICATION
        # -------------------------------------------------

        application = self._extract_application(text)

        # -------------------------------------------------
        # APPLICATION NOT FOUND
        # -------------------------------------------------

        if application is None:
            return self._decision(
                level=3,
                mode="os",
                task=text,
                intent=f"application.{action}",
                reason=(
                    "Genesis detected a possible application "
                    "operation, but the application target "
                    "could not be resolved."
                ),
                confidence=0.72,
                parameters={
                    "operation": action,
                    "requires_target": True,
                },
            )

        # =================================================
        # APPLICATION OPEN
        # =================================================

        if action == "open":
            # The case form ("Command Prompt") is preserved
            # in parameters["user_facing_target"] for
            # human-readable reporting. The `target` field
            # keeps the canonical id ("cmd") so executor
            # dispatch and existing tests that assert on
            # `plan.target == "chrome"` continue to work.
            user_facing_target = (
                getattr(self, "_last_case_form", "") or ""
            )
            return self._decision(
                level=3,
                mode="os",
                task=text,
                intent="application.open",
                application=application,
                target=application,
                reason=(
                    "The request explicitly asks Genesis "
                    "to open an application."
                ),
                confidence=0.97,
                parameters={
                    "operation": "open",
                    "user_facing_target": user_facing_target,
                },
            )

        # =================================================
        # APPLICATION CLOSE
        # =================================================

        if action == "close":
            return self._decision(
                level=3,
                mode="os",
                task=text,
                intent="application.close",
                application=application,
                target=application,
                reason=(
                    "The request explicitly asks Genesis "
                    "to close an application."
                ),
                confidence=0.97,
                parameters={
                    "operation": "close",
                },
            )

        # =================================================
        # APPLICATION INSPECT
        # =================================================

        if action == "inspect":
            return self._decision(
                level=3,
                mode="os",
                task=text,
                intent="application.inspect",
                application=application,
                target=application,
                reason=(
                    "The request asks Genesis to inspect "
                    "the state or status of an application."
                ),
                confidence=0.95,
                parameters={
                    "operation": "inspect",
                },
            )

        return None

    # =====================================================
    # EXTENDED LEVEL 3 INTENT DETECTION
    # =====================================================

    def _detect_extended_os_intent(self, text: str) -> Optional[Dict[str, Any]]:
        """Detect non-application OS capabilities without executing them."""
        text = self._normalize_text(text)

        if self._is_conversational_or_educational(text):
            # Same reasoning as the guard in _detect_os_intent: it
            # protects the regex layer, not the semantic resolver.
            semantic = self._semantic_fallback_for_guarded_text(text)
            if semantic is not None:
                return semantic
            return None

        # Strip politeness so patterns below match the actual
        # intent ("open chrome" rather than "could you open
        # chrome please").
        text = _strip_politeness(text)
        if not text:
            return None

        # -------------------------------------------------
        # 0. APPLICATION-TARGET PRIORITY
        # -------------------------------------------------
        # When the user says "open / launch / start <name>"
        # and <name> resolves to a KNOWN application alias
        # (File Explorer, Maps, Slack, etc.), the application
        # wins over every other interpretation: URL navigation,
        # file search, site shortcut, or file-family noun
        # patterns must NOT hijack the request.
        #
        # Without this priority gate the engine misroutes:
        #   * "open File Explorer" -> file.open (because "file"
        #     is a file-family noun and "explorer" is the rest)
        #   * "open Maps" -> browser.open_url (because "maps"
        #     is a Google Maps site alias)
        #   * "open my downloads" -> folder.open (correctly,
        #     because downloads is a folder not an app — and
        #     this gate is the ONLY reason downloads still
        #     routes to folder.open)
        #   * "open chrome" -> application.open (correctly)
        #
        # The gate consults the existing _extract_application
        # resolver, which already returns the canonical app
        # id for every alias including compound names. It is
        # the single source of truth for "is this an app?".
        #
        # Settings sub-pages (display, sound, network,
        # bluetooth, ...) are NOT applications — they are
        # ms-settings: URI navigations handled by the
        # existing system.open_settings regex. The gate
        # therefore excludes the settings sub-page noun set
        # so "open display settings" continues to route to
        # the settings path.
        _APP_OPEN_VERB_RE = re.compile(
            r"^(?:please\s+)?(?:open|launch|start|fire\s+up|"
            r"spin\s+up|boot\s+up|bring\s+up|start\s+up|"
            r"pop\s+open|pop\s+up)\s+(?:the\s+|my\s+)?(.+)$",
            re.IGNORECASE,
        )
        # Settings sub-page noun set — these are NEVER
        # applications, they are ms-settings: URI targets.
        # Two patterns:
        #   1. "<subpage> settings" (e.g. "display settings",
        #      "notifications settings")
        #   2. Bare "<subpage>" when the subpage is a known
        #      Windows settings subpage noun (e.g.
        #      "open notifications" is a settings subpage,
        #      not the Settings app's notifications screen)
        # The Windows Settings catalog in context_hint_resolver
        # is the source of truth for what counts as a
        # subpage noun; we mirror the same list here.
        _SETTINGS_SUBPAGE_NOUNS = frozenset({
            "display", "sound", "audio", "bluetooth",
            "wifi", "wi-fi", "network", "notifications",
            "notification", "privacy", "personalization",
            "appsfeatures", "apps", "windows update",
            "windows_update", "update", "accounts",
            "account", "dateandtime", "time", "language",
            "regionlanguage", "accessibility", "easeofaccess",
            "storage", "home",
        })
        # Build a regex that matches:
        #   * "<subpage> settings" / "<subpage> settings page"
        #   * bare "<subpage>" when the verb is open and
        #     there is no other noun in the request
        # We use a single pattern that ORs both forms.
        _settings_subpage_alt = (
            r"\b(?:" + "|".join(sorted(_SETTINGS_SUBPAGE_NOUNS, key=len, reverse=True)) + r")\s+settings?\b"
        )
        _settings_app_alt = (
            r"\b(?:settings|windows\s+settings|system\s+settings|"
            r"pc\s+settings|control\s+panel)\b"
        )
        _SETTINGS_SUBPAGE_NOUN_RE = re.compile(
            r"\b(?:"
            # "<subpage> settings" forms (e.g. "display
            # settings", "notifications settings", "windows
            # update")
            r"display\s+settings?|"
            r"sound\s+settings?|"
            r"audio\s+settings?|"
            r"bluetooth\s+settings?|"
            r"wifi\s+settings?|"
            r"wi-fi\s+settings?|"
            r"network\s+settings?|"
            r"notifications?\s+settings?|"
            r"privacy\s+settings?|"
            r"personalization\s+settings?|"
            r"apps?\s+settings?|"
            r"windows\s+update(?:settings)?|"
            r"update\s+settings?|"
            r"accounts?\s+settings?|"
            r"date\s+and\s+time|"
            r"time\s+settings?|"
            r"language\s+settings?|"
            r"region\s+and\s+language|"
            r"accessibility\s+settings?|"
            r"ease\s+of\s+access|"
            r"storage\s+settings?"
            r"|"
            # Settings app itself
            r"settings|"
            r"windows\s+settings|"
            r"system\s+settings|"
            r"pc\s+settings|"
            r"control\s+panel"
            r")\b",
            re.IGNORECASE,
        )
        m = _APP_OPEN_VERB_RE.match(text)
        if (
            m
            and not self._is_folder_anchor(text)
            and not _SETTINGS_SUBPAGE_NOUN_RE.search(text)
            # "open google maps" / "open apple maps" /
            # "open street map" are websites, not apps.
            # The site alias / URL gate below handles them.
            and not re.search(
                r"\b(?:google|apple|osm|openstreetmap|"
                r"openstreet|waze|here\s+we\s+go|"
                r"mapquest|tomtom)\b",
                text,
                re.IGNORECASE,
            )
        ):
            app = self._extract_application(text)
            if app is not None:
                # The canonical id is kept in `target` and
                # `application` (for executor dispatch and
                # existing test assertions). The user's
                # original case form is preserved in
                # `parameters["user_facing_target"]` for
                # human-readable reporting.
                return self._decision(
                    3, "os", text,
                    f"Open the {app} application.",
                    0.97,
                    intent="application.open",
                    application=app,
                    target=app,
                    parameters={
                        "operation": "open",
                        "user_facing_target": (
                            getattr(self, "_last_case_form", "") or ""
                        ),
                    },
                )

        # -------------------------------------------------
        # 1. BROWSER / WEB NAVIGATION
        # -------------------------------------------------
        # ------------------------------------------------------------
        # WEB.RESEARCH (live fetch + summarize) — must beat
        # browser.search for "search the web for X" / "look up X
        # online" / "find information about X" because the user
        # is asking for AI-mediated research, not just a literal
        # browser tab open. web.research is the Level-3 OS
        # intent that the WebIntelligence provider in
        # genesis_os/web_intelligence.py resolves with real
        # search backends (DuckDuckGo, etc.) and summarization.
        # ------------------------------------------------------------
        web_research = re.match(
            r"^(?:please\s+)?(?:"
            r"search\s+(?:the\s+)?(?:web|internet|online)\s+"
            r"(?:for|about)\s+(?P<q1>.+)"
            r"|look\s+up\s+(?P<q2>.+?)\s+online"
            r"|find\s+(?:information|info|details?)\s+about\s+(?P<q3>.+)"
            r"|research\s+(?P<q4>.+?)\s+online"
            r")\s*[?.!]?$",
            text,
            re.IGNORECASE,
        )
        if web_research:
            query = (
                web_research.group("q1")
                or web_research.group("q2")
                or web_research.group("q3")
                or web_research.group("q4")
                or ""
            ).strip()
            if query:
                return self._decision(
                    3, "os", text,
                    f"Live web research for '{query}'.",
                    0.95,
                    intent="web.research",
                    target=query,
                    parameters={"query": query},
                )

        m = re.fullmatch(r"(?:open|go to|visit)\s+(https?://\S+)", text)
        if m:
            return self._decision(3, "os", text, "Open a web URL.", 0.98,
                                  intent="browser.open_url", target=m.group(1),
                                  parameters={"url": m.group(1)})

        # Site-scoped search: "search youtube for python tutorials",
        # "search google for the latest AI news".
        site_search = re.match(
            r"(?:search|look\s+up)\s+(?:on\s+|in\s+)?"
            r"(youtube|google|bing|duckduckgo)\s+"
            r"(?:for|about)\s+(.+)",
            text,
        )
        if site_search:
            engine_name = site_search.group(1)
            search_query = site_search.group(2).strip()
            if search_query:
                return self._decision(3, "os", text, f"Search {engine_name} for '{search_query}'.", 0.96,
                                      intent="browser.search", target=search_query,
                                      parameters={"query": search_query, "engine": engine_name})

        # Web search with explicit engine or web keyword
        web_search = re.match(
            r"(?:search\s+(?:the\s+)?(?:web|internet|online)(?:\s+(?:for|about))?\s+|search\s+(?:for\s+)?(.+?)\s+on\s+(google|bing|duckduckgo|youtube)$|google\s+|look\s+up\s+(.+?)\s+online$)",
            text
        )
        if web_search:
            engine = "google"
            if " on " in text:
                parts = text.split(" on ")
                query = parts[0].replace("search for", "").replace("search", "").strip()
                engine = parts[1].strip() or "google"
            elif text.startswith("google "):
                query = text[7:].strip()
            elif "online" in text:
                query = text.replace("look up", "").replace("search", "").replace("online", "").replace("for", "").strip()
            else:
                query = text.replace("search the web for", "").replace("search the web about", "").replace("search web for", "").replace("search internet for", "").replace("search online for", "").strip()
            if query:
                return self._decision(3, "os", text, "The request asks Genesis to perform a browser search.", 0.96,
                                      intent="browser.search", target=query,
                                      parameters={"query": query, "engine": engine})

        # -------------------------------------------------
        # "this <document>" references
        # -------------------------------------------------
        # "search this PDF for X" / "find the section in this
        # document" / "summarize this Word file" — these are
        # references to a document the user already has open
        # or has been working with, NOT a web search. The
        # Document Agent owns these. This pattern fires
        # before the web-search default gate so "this PDF"
        # routes to L2 Document Agent (document.search)
        # rather than L3 browser.search.
        _THIS_DOCUMENT_RE = re.compile(
            r"^(?:please\s+)?"
            r"(?:search|find|look\s+for|read|summarize|open|"
            r"extract\s+(?:the\s+)?text\s+from|locate|highlight)\s+"
            r"(?:"
            # "this PDF" / "that document" — anaphoric
            # document references that the runtime entity
            # binder must resolve.
            r"(?:this|that)\s+"
            r"(?:pdf|document|spreadsheet|sheet|"
            r"presentation|docx?|xlsx?|file|essay|report|"
            r"paper|article|book)"
            r"|"
            # "the section about X" / "the chapter on Y" — the
            # user is asking about a section of a known
            # document. The "section|chapter|page|..."
            # alternative applies only to "the", not to
            # "this" or "that" (which are bare anaphoric
            # references and DO require runtime resolution).
            r"(?:the)\s+"
            r"(?:section|chapter|page|paragraph|line|"
            r"figure|table|heading|note)"
            r")"
            r"(?:\s+(?:for|about|with)\s+.+?)?$",
            re.IGNORECASE,
        )
        m_this_doc = _THIS_DOCUMENT_RE.match(text)
        if m_this_doc:
            full = m_this_doc.group(0)
            # Extract the query (everything after "for/with/about")
            query_match = re.search(
                r"\b(?:for|about|with)\s+[\"']?(.+?)[\"']?$",
                full,
                re.IGNORECASE,
            )
            query = query_match.group(1).strip() if query_match else ""
            # Determine the document kind from the captured
            # text (e.g. "this PDF" -> "pdf", "the section" ->
            # "section"). The kind text is the trailing noun
            # phrase.
            kind_match = re.search(
                r"(?:this|that|the)\s+(\S+)$",
                full,
                re.IGNORECASE,
            )
            if kind_match:
                # Strip the optional trailing query ("about X")
                # to recover the bare kind.
                kind_text = kind_match.group(1)
                kind = re.sub(
                    r"\s+(?:for|about|with)\s+.+$",
                    "",
                    kind_text,
                    flags=re.IGNORECASE,
                ).lower()
            else:
                kind = ""
            intent = "document.search" if query else "document.read"
            description = (
                f"Search inside {kind} file referenced as "
                "'this/that' (Document Agent)"
                if query
                else f"Read {kind} file referenced as 'this/that' (Document Agent)"
            )
            return self._decision(
                3, "os", text, description, 0.96,
                intent=intent,
                target="",
                parameters={
                    "document_kind": kind,
                    "query": query,
                    "anaphoric_target": True,
                    "requires_runtime_resolution": True,
                },
            )
        # A bare "search for X" / "find X" / "look up X" /
        # "google X" with NO filesystem anchor (no "in my
        # files", "on disk", a file extension, "my documents",
        # "my downloads", possessive "my X" where X is a file-
        # family noun, etc.) is a web search by default.
        #
        # Without this gate, the file.search regex below
        # catches every "search for X" and routes it to the
        # local filesystem, which is wrong for the generic
        # case. The web is the right default for an
        # unspecified "search for X" because the OS layer
        # is the only one with both:
        #   * a browser control capability (browser.search)
        #   * an actual web search provider
        # The agent layer cannot satisfy "search the web
        # for X" without the OS browser, so web ownership
        # belongs to L3.
        #
        # The gate is conservative: it only fires when the
        # request DOES NOT contain any filesystem anchor.
        # If the user says "find budget.xlsx in my
        # documents" the filesystem anchor wins and the
        # file.search path below takes over. The possessive
        # "my X" where X is a file-family noun (report,
        # document, file, essay, spreadsheet, ...) is also
        # a filesystem anchor because the user is asking
        # for THEIR file, not for the public web.
        _FILESYSTEM_ANCHOR_RE = re.compile(
            r"\b(?:in|on|inside|within|across)\s+(?:my|the|our)\s+"
            r"(?:files?|filesystem|disk|computer|laptop|pc|"
            r"downloads?|documents?|desktop|pictures?|music|"
            r"videos?|projects?|workspace|reports?|invoices?|"
            r"archive|backups?|notes?|home|folder|directory|"
            r"local\s+files?|clipboard)\b"
            r"|\b(?:my|the)\s+(?:local\s+)?(?:files?|filesystem|disk|clipboard)\b"
            r"|\.(?:txt|csv|json|xml|yaml|yml|pdf|docx?|xlsx?|xlsm?|"
            r"pptx?|py|js|ts|html|md|log|ini|conf|zip|tar|gz|rar|7z|"
            r"exe|bat|sh)\b"
            r"|\b(?:locate|find|search(?:\s+for)?|show\s+me)\s+"
            r"(?:the\s+|my\s+|our\s+)?"
            r"(?:latest|newest|most\s+recent|oldest)\s+"
            r"(?:file|document|spreadsheet|sheet|pdf|essay|"
            r"presentation|version|copy|backup)\b"
            r"|\bmy\s+(?:report|file|document|spreadsheet|sheet|"
            r"pdf|essay|presentation|cv|resume|notes?)\b"
            r"|\b(?:locate|find)\s+(?:a\s+)?(?:file|document|spreadsheet|"
            r"pdf|essay|presentation|photo|picture|video|song|track)\b"
            r"|\b(?:what(?:'s|\s+is)\s+in\s+(?:the\s+|my\s+)?clipboard\b)"
            # Research signals: "look up recent papers on X"
            # / "find papers about X" are L2 Research Agent
            # work, not web searches. The papers belong to
            # the academic literature.
            r"|\b(?:look\s+up|look\s+for|find)\s+(?:the\s+|my\s+|our\s+)?"
            r"(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:papers?|articles?|publications?|research|studies)\b"
            r"|\b(?:papers?|articles?|publications?)\s+(?:on|about|for|of)\b"
            r"|\brecent\s+papers?\b"
            r"|\bpapers?\s+(?:on|about|for|of)\b",
            re.IGNORECASE,
        )
        _DEFAULT_WEB_SEARCH_RE = re.compile(
            r"^(?:please\s+)?(?:"
            r"search(?:\s+(?:for|up))?\s+"
            r"|look\s+up\s+"
            r"|google\s+"
            r"|bing\s+"
            r"|duckduckgo\s+"
            r")(?P<query>\S.*)$",
            re.IGNORECASE,
        )
        m = _DEFAULT_WEB_SEARCH_RE.match(text)
        if m and not _FILESYSTEM_ANCHOR_RE.search(text):
            query = m.group("query").strip().rstrip(".?!")
            if query and len(query.split()) >= 1:
                # Detect a search engine hint at the end.
                engine = "google"
                lowered = query.lower()
                for eng in ("youtube", "bing", "duckduckgo"):
                    if lowered.endswith(" on " + eng) or lowered.endswith(" in " + eng):
                        engine = eng
                        query = query[: -(len(eng) + 4)].strip()
                        break
                if query:
                    return self._decision(
                        3, "os", text,
                        f"The request asks Genesis to perform a browser search for '{query}'.",
                        0.95,
                        intent="browser.search",
                        target=query,
                        parameters={"query": query, "engine": engine},
                    )

        # -------------------------------------------------
        # 1b. UNIVERSAL DESKTOP CONTROL (Level 3.10)
        # -------------------------------------------------

        if _SCREENSHOT_RE.fullmatch(text):
            return self._decision(3, "os", text, "Capture the screen.", 0.97,
                                  intent="screen.capture", target="screen",
                                  parameters={"capture": True})

        # Concept synonyms: meaning-based mapping for common
        # paraphrases of hardware controls.
        for synonym_re, concept in _CONCEPT_SYNONYMS:
            match = synonym_re.search(text)
            if not match:
                continue

            if concept in ("up", "down"):
                return self._decision(3, "os", text, f"Turn the brightness {concept}.", 0.95,
                                      intent="display.brightness_set",
                                      target=f"brightness {concept}",
                                      parameters={"direction": concept})
            if concept == "volume_up":
                return self._decision(3, "os", text, "Increase the volume.", 0.95,
                                      intent="volume.up", target="volume up",
                                      parameters={"steps": 2})
            if concept == "volume_down":
                return self._decision(3, "os", text, "Decrease the volume.", 0.95,
                                      intent="volume.down", target="volume down",
                                      parameters={"steps": 2})
            if concept == "mute":
                return self._decision(3, "os", text, "Mute the system volume.", 0.95,
                                      intent="volume.mute_toggle", target="volume",
                                      parameters={"mute": True})

        # YouTube playback must be checked BEFORE generic media
        # keys so "play despacito on youtube" opens YouTube
        # instead of toggling the media transport.
        youtube_play = _PLAY_ON_YOUTUBE_RE.match(text)
        if youtube_play:
            media_query = (youtube_play.group(1) or youtube_play.group(2) or "").strip()
            if media_query:
                return self._decision(3, "os", text, f"Play '{media_query}' on YouTube.", 0.96,
                                      intent="browser.search", target=media_query,
                                      parameters={"query": media_query, "engine": "youtube"})

        media_match = _MEDIA_ACTION_RE.match(text)
        if media_match:
            lowered = text.lower()
            if any(w in lowered for w in ("pause",)):
                action = "play_pause"
                verb = "pause"
            elif any(w in lowered for w in ("next", "skip")):
                action = "next"
                verb = "next track"
            elif any(w in lowered for w in ("previous", "go back")):
                action = "previous"
                verb = "previous track"
            elif lowered.startswith("stop"):
                action = "stop"
                verb = "stop"
            else:
                action = "play_pause"
                verb = "play"

            op = f"media.{action}" if action != "stop" else "media.stop"
            return self._decision(3, "os", text, f"{verb.capitalize()} media playback.", 0.95,
                                  intent=op, target=verb,
                                  parameters={"action": action})

        volume_set_match = _VOLUME_SET_RE.match(text)
        if volume_set_match:
            percent = int(volume_set_match.group(1))
            if 0 <= percent <= 100:
                return self._decision(3, "os", text, f"Set system volume to {percent}%.", 0.97,
                                      intent="volume.set", target=f"volume {percent}",
                                      parameters={"percent": percent})

        bare_mute_match = _BARE_MUTE_RE.match(text)
        if bare_mute_match:
            mute_on = bare_mute_match.group(1).lower() == "mute"
            return self._decision(3, "os", text, "Mute the system volume." if mute_on else "Unmute the system volume.", 0.96,
                                  intent="volume.mute_toggle", target="volume",
                                  parameters={"mute": mute_on})

        volume_match = _VOLUME_RE.match(text)
        if volume_match:
            keyword = volume_match.group(1).lower()
            if keyword in ("mute", "silent"):
                return self._decision(3, "os", text, "Mute the system volume.", 0.96,
                                      intent="volume.mute_toggle", target="volume",
                                      parameters={"mute": True})
            if keyword == "unmute":
                return self._decision(3, "os", text, "Unmute the system volume.", 0.96,
                                      intent="volume.mute_toggle", target="volume",
                                      parameters={"mute": False})
            if keyword in ("max", "full"):
                return self._decision(3, "os", text, "Set system volume to 100%.", 0.97,
                                      intent="volume.set", target="volume 100",
                                      parameters={"percent": 100})
            direction = keyword
            case_form = getattr(self, "_last_case_form", "") or ""
            steps = 1 if ("a bit" in case_form.lower() or "a little" in case_form.lower()) else 2
            return self._decision(3, "os", text, f"Turn the volume {direction}.", 0.96,
                                  intent=f"volume.{direction}", target=f"volume {direction}",
                                  parameters={"steps": steps})

        brightness_set_match = _BRIGHTNESS_SET_RE.match(text)
        if brightness_set_match:
            percent = int(brightness_set_match.group(1))
            if 0 <= percent <= 100:
                return self._decision(3, "os", text, f"Set screen brightness to {percent}%.", 0.97,
                                      intent="display.brightness_set", target=f"brightness {percent}",
                                      parameters={"percent": percent})

        brightness_step_match = _BRIGHTNESS_STEP_RE.match(text)
        if brightness_step_match:
            direction = brightness_step_match.group(1).lower()
            return self._decision(3, "os", text, f"Turn the brightness {direction}.", 0.96,
                                  intent="display.brightness_set", target=f"brightness {direction}",
                                  parameters={"direction": direction})

        if re.search(r"\bbrightness\b", text) and re.search(
            r"\b(how\s+|what(?:'s| is)\s+the\s+)(?:current\s+)?brightness", text
        ):
            return self._decision(3, "os", text, "Read current screen brightness.", 0.96,
                                  intent="display.brightness_get", target="brightness")

        battery_match = _BATTERY_RE.search(text)
        if battery_match and len(text) <= 40:
            return self._decision(3, "os", text, "Report battery status.", 0.96,
                                  intent="hardware.battery", target="battery")

        perf_match = _SYSTEM_PERF_RE.search(text)
        if perf_match and len(text) <= 60:
            return self._decision(3, "os", text, "Report CPU, memory and uptime snapshot.", 0.96,
                                  intent="hardware.stats", target="system performance")

        clipboard_copy_match = _CLIPBOARD_COPY_RE.match(text)
        if clipboard_copy_match:
            clip_text = clipboard_copy_match.group(1) or clipboard_copy_match.group(2)
            case_form = getattr(self, "_last_case_form", "") or ""
            case_match = _CLIPBOARD_COPY_RE.match(case_form) or _CLIPBOARD_COPY_RE.match(text)
            if case_match and (case_match.group(1) or case_match.group(2)):
                clip_text = case_match.group(1) or case_match.group(2)
            return self._decision(3, "os", text, "Copy text to the clipboard.", 0.96,
                                  intent="clipboard.copy", target="clipboard",
                                  parameters={"text": clip_text})

        if _CLIPBOARD_READ_RE.match(text):
            return self._decision(3, "os", text, "Read the clipboard content.", 0.96,
                                  intent="clipboard.paste", target="clipboard")

        lock_match = _LOCK_WORKSTATION_RE.match(text)
        if lock_match:
            return self._decision(3, "os", text, "Lock the workstation; confirmation required.", 0.97,
                                  intent="workstation.lock", target="workstation",
                                  parameters={"confirmed": False, "requires_confirmation": True})

        # -------------------------------------------------
        # 1c. LIVE WEB RESEARCH (Level 3.11)
        #
        # Distinct from browser.search: this fetches live
        # results INTO the conversation instead of only
        # opening a browser tab.
        #
        # ARCHITECTURAL FIX (per GENESIS_MASTER_COMPLETION
        # directive): "Research X" must go to the L2 Research
        # Agent, not the OS layer. "Search the web for X"
        # and "look up X online" go to OS web.research because
        # they explicitly request web fetching.
        # -------------------------------------------------

        web_research_match = re.match(
            r"^(?:search\s+(?:the\s+)?(?:web|internet|online)\s+"
            r"(?:for|about)|look\s+up\s+(?:.+?\s+)?online|"
            r"web\s+search(?:\s+for)?)\s+(.+?)(?:\s+and\s+(?:tell\s+me|summarize|report))?$",
            text,
        )
        if web_research_match:
            query_text = web_research_match.group(1).strip()
            if len(query_text.split()) >= 1 and query_text not in ("this", "that"):
                return self._decision(3, "os", text, f"Research '{query_text}' on the live web.", 0.95,
                                      intent="web.research", target=query_text,
                                      parameters={"query": query_text})

        # -------------------------------------------------
        # 1d. WEBSITE SHORTCUTS (3.12)
        # -------------------------------------------------

        open_site = _OPEN_SITE_RE.match(text)
        if open_site:
            site_key = open_site.group(1).strip().lower()
            url = _SITE_ALIASES.get(site_key)
            if url:
                return self._decision(3, "os", text, f"Open {site_key}.", 0.97,
                                      intent="browser.open_url", target=url,
                                      parameters={"url": url, "site": site_key})

        # -------------------------------------------------
        # 1e. WINDOW MANAGEMENT (3.12)
        # -------------------------------------------------

        for pattern, (op, verb, description) in _WINDOW_OPS.items():
            if re.match(pattern, text):
                return self._decision(3, "os", text, description, 0.96,
                                      intent=op, target="windows")

        # -------------------------------------------------
        # 1f. DAILY INTELLIGENCE (3.12)
        # -------------------------------------------------

        weather_match = _WEATHER_RE.match(text)
        if weather_match:
            city = (weather_match.group("city") or weather_match.group("city2") or "").strip()
            if city:
                return self._decision(3, "os", text, f"Check the weather in {city}.", 0.95,
                                      intent="web.weather", target=city,
                                      parameters={"city": city})

        clock_match = _WORLD_CLOCK_RE.match(text)
        if clock_match:
            city = (
                clock_match.group("city")
                or clock_match.group("city2")
                or ""
            ).strip()
            if city:
                return self._decision(3, "os", text, f"Check the current time in {city}.", 0.96,
                                      intent="time.world_clock", target=city,
                                      parameters={"city": city})

        storage_match = _STORAGE_RE.search(text)
        if storage_match and re.search(
            r"\b(how much|how many|check|storage left|space left|free)\b", text
        ) and len(text) <= 60:
            return self._decision(3, "os", text, "Report disk space.", 0.95,
                                  intent="hardware.storage", target="storage")

        math_match = _MATH_RE.match(text)
        if math_match:
            expression = math_match.group("expr").strip().rstrip("?").strip()

            percent_match = _PERCENT_OF_RE.match(expression)
            if percent_match:
                pct = float(percent_match.group("pct"))
                num = float(percent_match.group("num"))
                expression = f"{pct} / 100 * {num}"
            else:
                # Strip a trailing '=' users often type.
                expression = expression.rstrip("=").strip()

                if not re.fullmatch(
                    r"[\d\s\.\+\-\*/%\(\)]*(?:\*\*)?[\d\s\.\+\-\*/%\(\)]*",
                    expression,
                ):
                    math_match = None

            if math_match is not None and any(ch.isdigit() for ch in expression):
                return self._decision(3, "os", text, "Evaluate the arithmetic.", 0.96,
                                      intent="math.evaluate", target=expression,
                                      parameters={"expression": expression})

        # Long-term memory: "remember that X" / "remember to X".
        # This is the long-term memory store operation; the
        # L1 conversation layer handles it via the
        # LongTermMemory component (see
        # memory/long_term_memory.py). It is NOT a notes.create
        # operation; the user is talking to the AI, not
        # creating an OS note.
        remember_match = _REMEMBER_RE.match(text)
        if remember_match:
            return self._decision(
                level=1,
                mode="conversation",
                task=text,
                intent="memory.store",
                reason=(
                    "The user is asking the long-term memory "
                    "subsystem to remember a fact. This is an "
                    "L1 conversation operation; the AI engine "
                    "stores the fact in the user's persistent "
                    "profile."
                ),
                confidence=0.95,
                parameters={
                    "remember_text": (
                        (remember_match.group("text")
                         or remember_match.group("text2")
                         or "").strip()
                    ),
                    "memory_operation": "store",
                },
            )

        note_create = _NOTE_CREATE_RE.match(text)
        if note_create:
            case_form = getattr(self, "_last_case_form", "") or ""
            note_text = (
                note_create.group("text")
                or note_create.group("text2")
            )
            case_note = _NOTE_CREATE_RE.match(case_form or text)
            if case_note:
                note_text = (
                    case_note.group("text")
                    or case_note.group("text2")
                )
            if note_text and note_text.strip():
                return self._decision(3, "os", text, "Save your note.", 0.96,
                                      intent="notes.create", target="notes",
                                      parameters={"text": note_text.strip()})

        if _NOTES_LIST_RE.match(text):
            return self._decision(3, "os", text, "List your saved notes.", 0.96,
                                  intent="notes.list", target="notes")

        install_match = _INSTALL_RE.match(text)
        if install_match:
            package_name = install_match.group("package").strip()
            verb = text.split()[0].lower()
            op = f"package.{verb}"
            return self._decision(3, "os", text, f"{verb.capitalize()} '{package_name}'; confirmation required.", 0.96,
                                  intent=op, target=package_name,
                                  parameters={"package": package_name, "confirmed": False,
                                              "requires_confirmation": True})

        if _RECYCLE_QUERY_RE.match(text):
            return self._decision(3, "os", text, "Check Recycle Bin contents size.", 0.96,
                                  intent="cleanup.recycle_bin_query", target="recycle bin")

        if _RECYCLE_BIN_RE.match(text):
            return self._decision(3, "os", text, "Empty the Recycle Bin; confirmation required.", 0.97,
                                  intent="cleanup.empty_recycle_bin", target="recycle bin",
                                  parameters={"confirmed": False, "requires_confirmation": True})

        # -------------------------------------------------
        # 2. WINDOWS SETTINGS
        # -------------------------------------------------
        settings = {
            "wifi": ("wifi", "network-wifi"),
            "wi-fi": ("wifi", "network-wifi"),
            "network": ("network", "network"),
            "bluetooth": ("bluetooth", "bluetooth"),
            "display": ("display", "display"),
            "sound": ("sound", "sound"),
            "privacy": ("privacy", "privacy"),
            "notifications": ("notifications", "notifications"),
            "notification": ("notifications", "notifications"),
            "windows update": ("windows update", "windowsupdate"),
            "windows_update": ("windows update", "windowsupdate"),
            "personalization": ("personalization", "personalization"),
            "apps": ("appsfeatures", "appsfeatures"),
            "apps features": ("appsfeatures", "appsfeatures"),
            "accounts": ("accounts", "accounts"),
            "account": ("accounts", "accounts"),
            "time": ("dateandtime", "dateandtime"),
            "language": ("regionlanguage", "regionlanguage"),
            "accessibility": ("easeofaccess", "easeofaccess"),
            "ease of access": ("easeofaccess", "easeofaccess"),
            "storage": ("storage", "storage"),
            "home": ("home", "home"),
        }
        m = re.fullmatch(r"(?:open|go to)\s+(.+?)\s+settings", text)
        if m:
            key = m.group(1).strip()
            if key in settings:
                return self._decision(3, "os", text, "The request asks Genesis to open a supported system settings page.", 0.98,
                                      intent="system.open_settings", target=settings[key][0],
                                      parameters={"settings": settings[key][1]})
        # "open windows update" (no trailing "settings")
        m2 = re.fullmatch(r"(?:open|go to)\s+(windows\s+update)", text)
        if m2:
            return self._decision(3, "os", text, "The request asks Genesis to open a supported system settings page.", 0.97,
                                  intent="system.open_settings", target="windows update",
                                  parameters={"settings": "windowsupdate"})

        # -------------------------------------------------
        # 3. WI-FI CONTROL
        # -------------------------------------------------
        if text in ("list wifi", "show wifi", "list wi-fi", "scan wifi", "available wifi", "show available networks"):
            return self._decision(3, "os", text, "List available Wi-Fi networks.", 0.97,
                                  intent="network.list_wifi", target="wifi")

        m = re.search(r"connect\s+(?:to\s+)?(?:wifi|wi-fi)\s+['\"]?(.+?)['\"]?\s+password\s+['\"]?(.+?)['\"]?$", text)
        if m:
            ssid, password = m.group(1).strip(), m.group(2).strip()
            if ssid and password:
                return self._decision(3, "os", text, "The request asks Genesis to connect the computer to Wi-Fi.", 0.99,
                                      intent="network.connect_wifi", target=ssid,
                                      parameters={"ssid": ssid, "password": password, "confirmed": False})

        # -------------------------------------------------
        # 4. SPREADSHEET INTELLIGENCE (Level 3.14+)
        # -------------------------------------------------
        #
        # Standalone spreadsheet operations. The marks-
        # ranking workflow from the directive is a COMPOUND
        # task handled by the compound path; this section
        # handles the individual operations the user might
        # type in isolation.

        sort_match = re.match(
            r"^(?:please\s+)?sort\s+(?:the\s+|my\s+)?(?:spreadsheet|sheet|workbook|data)\s+"
            r"(?:by\s+|on\s+)?(.+?)(?:\s+descending|\s+ascending)?$",
            text,
        )
        if sort_match:
            column = sort_match.group(1).strip()
            descending = "descending" in text
            return self._decision(
                3, "os", text,
                f"Sort the spreadsheet by '{column}'.",
                0.96,
                intent="spreadsheet.sort",
                target="spreadsheet",
                parameters={"column": column, "descending": descending},
            )

        filter_match = re.match(
            r"^(?:please\s+)?filter\s+(?:the\s+|my\s+)?(?:spreadsheet|sheet|workbook|data)?\s*"
            r"(?:where|when|if)?\s*(.+?)\s*(?:equals|is|=|>|<|>=|<=)\s*(.+?)$",
            text,
        )
        if filter_match:
            column = filter_match.group(1).strip()
            value = filter_match.group(2).strip()
            return self._decision(
                3, "os", text,
                f"Filter the spreadsheet where {column} = {value}.",
                0.95,
                intent="spreadsheet.filter",
                target="spreadsheet",
                parameters={"column": column, "value": value, "condition": "equals"},
            )

        rank_match = re.match(
            r"^(?:please\s+)?rank\s+(?:the\s+)?(.+?)(?:\s+by\s+(.+?))?(?:\s+(?:descending|ascending))?$",
            text,
        )
        if rank_match:
            target_phrase = rank_match.group(1).strip()
            by_phrase = rank_match.group(2)
            by_phrase = by_phrase.strip() if by_phrase else "score"
            descending = "descending" in text
            return self._decision(
                3, "os", text,
                f"Rank the records by '{by_phrase}'.",
                0.94,
                intent="spreadsheet.rank",
                target=target_phrase or "records",
                parameters={"rank_column": by_phrase, "descending": descending},
            )

        if re.match(
            r"^(?:please\s+)?(?:sum|add(?:\s+up)?|total|compute(?:\s+the)?\s+total|"
            r"give\s+me\s+the\s+total|count(?:\s+the)?)\s+"
            r"(?:the\s+|all\s+(?:the\s+)?)?(?:totals?|values|numbers|amounts?|sums?)\b",
            text,
        ):
            return self._decision(
                3, "os", text, "Aggregate the spreadsheet column/totals.", 0.96,
                intent="spreadsheet.aggregate", target="spreadsheet",
                parameters={"operation": "sum"},
            )

        if re.match(
            r"^(?:please\s+)?(?:calculate|compute)\s+"
            r"(?:the\s+)?(?:average|mean|sum|total|min|max|median)\s+"
            r"(?:for|of)\s+(?:each|every|the|column|row)?\s*(.+?)$",
            text,
        ):
            return self._decision(
                3, "os", text,
                "Calculate the aggregate over the spreadsheet.",
                0.94,
                intent="spreadsheet.aggregate",
                target="spreadsheet",
                parameters={"operation": "mean"},
            )

        if re.match(
            r"^(?:please\s+)?group\s+(?:the\s+)?data\s+by\s+(.+?)$",
            text,
        ):
            column = re.match(
                r"^(?:please\s+)?group\s+(?:the\s+)?data\s+by\s+(.+?)$", text
            ).group(1).strip()
            return self._decision(
                3, "os", text,
                f"Group the data by '{column}'.",
                0.94,
                intent="spreadsheet.group_by",
                target="spreadsheet",
                parameters={"column": column},
            )

        # -------------------------------------------------
        # 5. PROCESS INTELLIGENCE
        # -------------------------------------------------
        if re.match(r"(?:list|show|get|display)\s+(?:all\s+)?(?:running\s+)?processes\b", text) or text in ("running processes", "active processes", "process list"):
            return self._decision(3, "os", text, "List running system processes.", 0.97,
                                  intent="process.list", target="computer",
                                  parameters={"limit": 500})

        inspect_proc = re.match(r"(?:inspect|check)\s+process\s+['\"]?(.+?)['\"]?$", text)
        if inspect_proc:
            proc_target = inspect_proc.group(1).strip()
            return self._decision(3, "os", text, f"Inspect process '{proc_target}'.", 0.97,
                                  intent="process.inspect", target=proc_target,
                                  parameters={"process": proc_target})

        # -------------------------------------------------
        # 5. FOLDER OPERATIONS
        # -------------------------------------------------
        # Special-case: "show my notes" / "read my notes" /
        # "list my notes" / "open my notes" all mean the
        # Notes feature (notes.list), not a folder called
        # "notes". The notes.create / notes.list patterns
        # below at section 12 catch this case correctly, but
        # the broad "show my <folder>" pattern at the top of
        # section 5 would otherwise match "notes" as a
        # folder and route to folder.open. This guard runs
        # BEFORE the folder-open pattern so the notes.list
        # intent wins.
        notes_match = re.match(
            r"^(?:please\s+)?(?:show\s+me\s+my|show\s+my|"
            r"read\s+my|list\s+my|open\s+my|view\s+my|"
            r"display\s+my|get\s+my)\s+notes?\s*[?.!]?$",
            text,
        )
        if notes_match:
            return self._decision(
                3, "os", text, "List your saved notes.", 0.96,
                intent="notes.list", target="notes",
            )

        # Open standard user folder
        open_folder_std = re.match(
            r"(?:open|show(?:\s+me)?|explore|go\s+to|take\s+me\s+to|navigate\s+to)\s+"
            r"(?:my\s+|the\s+)?"
            r"(downloads?|documents?|desktop|pictures?|music|"
            r"videos?|projects?|workspace|reports?|invoices?|archive|"
            r"backups?|temp|scratch|home|root)"
            r"(?:\s+folder)?$",
            text
        )
        if not open_folder_std:
            # TYPO TOLERANCE: "open my downloadss", "go to documnts".
            fuzzy_folder = re.match(
                r"(?:open|show(?:\s+me)?|explore|go\s+to|take\s+me\s+to)\s+"
                r"(?:my\s+|the\s+)?([a-z]+)(?:\s+folder)?$",
                text,
            )
            if fuzzy_folder:
                from difflib import get_close_matches as _gcm

                close = _gcm(
                    fuzzy_folder.group(1),
                    (
                        "downloads", "documents", "desktop",
                        "pictures", "music", "videos",
                        "project", "workspace", "reports",
                        "invoices", "archive", "backups",
                        "notes", "home",
                    ),
                    n=1,
                    cutoff=0.84,
                )
                if close:
                    open_folder_std = fuzzy_folder
                    folder_name = close[0]
                    return self._decision(3, "os", text, f"Open the {folder_name} folder.", 0.94,
                                          intent="folder.open", target=folder_name,
                                          parameters={"folder": folder_name})
        if open_folder_std:
            folder_name = open_folder_std.group(1).strip()
            return self._decision(3, "os", text, f"Open the {folder_name} folder.", 0.98,
                                  intent="folder.open", target=folder_name,
                                  parameters={"folder": folder_name})

        open_folder_explicit = _FOLDER_OPEN_EXPLICIT_RE.match(text)
        if open_folder_explicit:
            case_form = getattr(self, "_last_case_form", "") or ""
            case_match = _FOLDER_OPEN_EXPLICIT_RE.match(case_form)
            folder_target = (
                case_match.group(1).strip()
                if case_match
                else open_folder_explicit.group(1).strip()
            )
            return self._decision(3, "os", text, f"Open folder '{folder_target}'.", 0.98,
                                  intent="folder.open", target=folder_target,
                                  parameters={"folder": folder_target})

        # Create folder
        create_folder_match = _FOLDER_CREATE_RE.match(text)
        if create_folder_match:
            case_form = getattr(self, "_last_case_form", "") or ""
            case_match = _FOLDER_CREATE_RE.match(case_form)
            folder_name = (
                case_match.group(1).strip()
                if case_match
                else create_folder_match.group(1).strip()
            )
            return self._decision(3, "os", text, f"Create folder '{folder_name}'.", 0.98,
                                  intent="folder.create", target=folder_name,
                                  parameters={"folder": folder_name})

        # Save X to my Y folder (folder.create so the
        # folder is guaranteed to exist when the L2 agent's
        # output is written into it).
        save_to_folder_match = _SAVE_TO_FOLDER_RE.match(text)
        if save_to_folder_match:
            case_form = getattr(self, "_last_case_form", "") or ""
            case_match = _SAVE_TO_FOLDER_RE.match(case_form)
            folder_name = (
                case_match.group(1).strip()
                if case_match
                else save_to_folder_match.group(1).strip()
            )
            return self._decision(
                3, "os", text,
                f"Ensure folder '{folder_name}' exists so the "
                f"result can be saved into it.",
                0.97,
                intent="folder.create",
                target=folder_name,
                parameters={
                        "folder": folder_name,
                        "save_intent": True,
                        "source_clause": "save_to_folder",
                },
            )

        # Organize folder
        organize_match = re.match(
            r"organize\s+(?:my\s+)?(downloads|documents|desktop|files)(?:\s+folder)?$",
            text
        )
        if organize_match:
            target_area = organize_match.group(1).strip()
            return self._decision(3, "os", text, f"Organize {target_area}.", 0.96,
                                  intent="folder.organize", target=target_area,
                                  parameters={"folder": target_area})

        # Delete folder (confirmation required)
        # Two phrasings supported:
        #   * "delete folder <name>"  ("delete folder old_stuff")
        #   * "delete <name> folder"  ("delete downloads folder",
        #                              "delete the empty old_stuff
        #                              folder")
        delete_folder_match = re.match(
            r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+|my\s+|an?\s+)?"
            r"(?:empty\s+)?folder\s+['\"]?(.+?)['\"]?$",
            text,
        ) or re.match(
            r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+|my\s+|an?\s+)?"
            r"(?:empty\s+)?['\"]?(.+?)['\"]?\s+folder\s*[?.!]?$",
            text,
        )
        if delete_folder_match:
            target_area = delete_folder_match.group(1).strip()
            return self._decision(
                3, "os", text,
                f"Delete folder '{target_area}'; explicit confirmation required.",
                0.97,
                intent="folder.delete", target=target_area,
                parameters={
                    "folder": target_area,
                    "confirmed": False,
                    "requires_confirmation": True,
                },
            )

        # Rename folder (confirmation required)
        # Matches:
        #   * "rename folder X to Y"
        #   * "rename X folder to Y"  ("rename the projects
        #                                folder to archives")
        rename_folder_match = (
            re.match(
                r"^(?:please\s+)?rename\s+(?:the\s+)?folder\s+"
                r"['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?$",
                text,
            )
            or re.match(
                r"^(?:please\s+)?rename\s+(?:the\s+)?['\"]?(.+?)['\"]?"
                r"\s+folder\s+to\s+['\"]?(.+?)['\"]?$",
                text,
            )
        )
        if rename_folder_match:
            old_name = rename_folder_match.group(1).strip()
            new_name = rename_folder_match.group(2).strip()
            return self._decision(
                3, "os", text,
                f"Rename folder '{old_name}' to '{new_name}'; explicit confirmation required.",
                0.97,
                intent="folder.rename",
                target=old_name,
                parameters={
                    "folder": old_name,
                    "new_name": new_name,
                    "confirmed": False,
                    "requires_confirmation": True,
                },
            )

        # Move files
        move_match = _MOVE_FILES_RE.match(text)
        if move_match:
            case_form = getattr(self, "_last_case_form", "") or ""
            case_match = _MOVE_FILES_RE.match(case_form)
            dest = (
                case_match.group(1).strip()
                if case_match
                else move_match.group(1).strip()
            )
            return self._decision(3, "os", text, f"Move files to '{dest}'.", 0.95,
                                  intent="file.move", target=dest,
                                  parameters={"destination": dest, "requires_confirmation": True, "confirmed": False})

        # -------------------------------------------------
        # 6. LOCAL FILESYSTEM / FILE SEARCH & DISCOVERY
        # -------------------------------------------------
        local_find_match = re.match(
            r"(?:find|search\s+for|show\s+me|locate)\s+(?:the\s+|my\s+)?(?:files?\s+(?:named\s+|related\s+to\s+|about\s+)?|documents?\s+|presentation\s+|essay\s+|spreadsheet\s+|sheet\s+|pdf\s+)?['\"]?(.+?)['\"]?$",
            text
        )
        if local_find_match:
            raw_target = local_find_match.group(1).strip()
            if raw_target and raw_target not in ("how", "why", "what", "where", "when", "who", "an ielts essay"):
                query = text
                for pfx in (
                    "find my ", "find the ", "find ",
                    "show me the files related to ", "show me files related to ",
                    "show me the files for ", "show me files for ",
                    "search for files named ", "search for files matching ",
                    "search for files related to ", "search for files ", "search for ",
                    "locate my ", "locate the ", "locate "
                ):
                    if text.startswith(pfx):
                        query = text[len(pfx):].strip()
                        break
                return self._decision(3, "os", text, "Search local filesystem for matching files.", 0.96,
                                      intent="file.search", target=query or raw_target,
                                      parameters={"query": query or raw_target})

        # Explicit file path operations (read, open, inspect)
        file_match = re.search(r"(?:read|open|inspect|check)\s+(?:the\s+)?(?:file\s+)?['\"]?([^'\"]+\.(?:txt|csv|json|xml|yaml|yml|pdf|docx?|xlsx?|xlsm?|pptx?|py|js|ts))['\"]?", text)
        if file_match:
            target = file_match.group(1).strip()
            verb = text.split()[0]
            operation = "file.read" if verb == "read" else "file.open" if verb == "open" else "file.inspect"
            return self._decision(3, "os", text, "The request targets a specific file operation.", 0.96,
                                  intent=operation, target=target, parameters={"operation": operation})

        # Natural file open: "open the PDF I downloaded yesterday", "open my resume"
        natural_open_file = _NATURAL_OPEN_FILE_RE.match(text)
        if natural_open_file:
            case_form = getattr(self, "_last_case_form", "") or ""
            case_match = _NATURAL_OPEN_FILE_RE.match(case_form)
            if case_match:
                file_desc = f"{case_match.group(1)} {case_match.group(2)}".strip()
            else:
                file_desc = f"{natural_open_file.group(1)} {natural_open_file.group(2)}".strip()
            return self._decision(3, "os", text, f"Open {file_desc}.", 0.95,
                                  intent="file.open", target=file_desc,
                                  parameters={"description": file_desc})

        # -------------------------------------------------
        # ANAPHORIC FILE QUERIES
        # -------------------------------------------------
        # "open the latest PDF from my downloads",
        # "show me the most recent spreadsheet in downloads",
        # "what did I download yesterday", "find the PDF I
        # worked on last week", etc. The exact file is
        # anaphoric ("the latest one", "yesterday's") and
        # must be resolved at runtime by the session
        # binder; the engine's job is only to route to L3
        # with a recognisable intent so the runtime knows
        # what to do.
        #
        # These patterns run BEFORE the application-name
        # fallback below (which would otherwise route
        # "open the latest PDF" to application.open with
        # requires_target=True) so the engine does not
        # collapse the anaphoric reference to a generic
        # "open some app" decision.
        _ANAPHORIC_FILE_RE = re.compile(
            r"^(?:please\s+)?"
            r"(?:"
            # "open the latest X from my Y" / "open the
            # newest X" / "open the X from yesterday"
            r"open\s+(?:the\s+)?(?:latest|newest|most\s+recent|"
            r"oldest|last|previous|active|current)\s+"
            r"(?P<anaph_kind>file|document|spreadsheet|sheet|"
            r"pdf|presentation|photo|picture|video|song|track|"
            r"image|archive|backup|version|copy)\b"
            r"|"
            # "open the X from Y" / "open the X I worked on Y"
            r"open\s+(?:the\s+|my\s+)?(?P<anaph_kind2>file|document|"
            r"spreadsheet|sheet|pdf|presentation|photo|picture|"
            r"video|song|track|image|archive|backup|version|copy|"
            r"essay|report)\s+(?:from|of|in|on)\b"
            r"|"
            # "show me the most recent X in Y" / "show me the
            # latest X from Y"
            r"show\s+me\s+(?:the\s+)?(?:latest|newest|most\s+recent|"
            r"oldest)\s+(?P<anaph_kind3>file|document|spreadsheet|"
            r"sheet|pdf|presentation|photo|picture|video|song|"
            r"track|image|archive|backup|version|copy)\b"
            r"|"
            # "what did I download / open / save Y"
            r"what\s+did\s+I\s+(?:download|open|save|create|"
            r"receive|get|fetch)\b"
            r"|"
            # "show me what I downloaded / opened / saved"
            r"show\s+me\s+what\s+I\s+(?:downloaded|opened|saved|"
            r"created|received|got|fetched)\b"
            r"|"
            # "find the X I worked on / edited / saved Y"
            r"find\s+(?:the\s+|my\s+)?(?P<anaph_kind4>file|document|"
            r"spreadsheet|sheet|pdf|presentation|photo|picture|"
            r"video|song|track|image|archive|backup|version|copy|"
            r"essay|report)\s+(?:i|that\s+i|which\s+i)\b"
            r"|"
            # "open the latest X spreadsheet" — spreadsheet
            # kind appears AFTER the anaphoric adjective.
            r"open\s+(?:the\s+)?(?:latest|newest|most\s+recent|"
            r"oldest)\s+\w*\s*"
            r"(?P<anaph_kind5>spreadsheet|sheet|workbook)\b"
            r"|"
            # "open the X from yesterday" where X is a
            # file family
            r"open\s+(?:the\s+|my\s+)?(?P<anaph_kind6>file|document|"
            r"spreadsheet|sheet|pdf|presentation|photo|picture|"
            r"video|song|track|image|archive|backup|version|copy|"
            r"essay|report)\s+from\s+yesterday\b"
            r")",
            re.IGNORECASE,
        )
        m_anaphoric = _ANAPHORIC_FILE_RE.match(text)
        if m_anaphoric:
            # Determine the kind for intent selection:
            # spreadsheet/sheet -> spreadsheet.inspect;
            # otherwise -> file.open.
            kind_text = ""
            for g in (
                "anaph_kind", "anaph_kind2", "anaph_kind3",
                "anaph_kind4", "anaph_kind5", "anaph_kind6",
            ):
                v = m_anaphoric.group(g)
                if v:
                    kind_text = v
                    break
            if kind_text in ("spreadsheet", "sheet", "workbook"):
                anaph_intent = "spreadsheet.inspect"
                description_kind = "spreadsheet"
            else:
                anaph_intent = "file.open"
                description_kind = "file"
            return self._decision(
                3, "os", text,
                f"Anaphoric {description_kind} reference: the "
                "specific file is contextual and must be "
                "resolved by the session binder at runtime "
                "(e.g. 'the latest PDF' becomes the most "
                "recently downloaded PDF).",
                0.95,
                intent=anaph_intent,
                target="",
                parameters={
                    "source_is_anaphoric": True,
                    "requires_target": True,
                    "requires_runtime_resolution": True,
                },
            )

        # File deletion (confirmation required)
        delete_match = re.search(r"(?:delete|remove)\s+(?:the\s+)?(?:file\s+)?['\"]?([^'\"]+\.[A-Za-z0-9]{1,8})['\"]?", text)
        if delete_match:
            target = delete_match.group(1).strip()
            return self._decision(3, "os", text, "The request asks to delete a file; explicit confirmation is required.", 0.99,
                                  intent="file.delete", target=target,
                                  parameters={"confirmed": False, "requires_confirmation": True})

        # -------------------------------------------------
        # GUI TYPE / PASTE (focused window input)
        # -------------------------------------------------
        # "write Hello in notepad" / "type \"Hello World\" into
        # notepad" / "enter text foo" / "fill in bar" / "input
        # baz in notepad" / "paste Hello". Resolves to
        # gui.type_text / gui.paste_text so the executor's
        # GUIController drives pyautogui into whichever window
        # currently has focus (target=None) or into the named
        # window ("notepad" -> target="notepad"). The
        # gui.focus_window step is dispatched automatically
        # by the executor when the plan carries a non-empty
        # target, so the user's request flows through with
        # no extra phrasing required.
        gui_type = _GUI_TYPE_TEXT_RE.match(text)
        if gui_type:
            payload = (
                gui_type.group("qtext")
                or gui_type.group("stext")
                or gui_type.group("utext")
                or ""
            ).strip()
            target = (gui_type.group("target") or "").strip() or None
            verb = text.split(None, 1)[0].lower()
            intent = "gui.paste_text" if verb == "paste" else "gui.type_text"
            if not payload:
                return None
            # Length guard: typing into a focused window is a
            # short literal payload ("Hello", "Hello World",
            # "my name is Bob"). Long payloads (an essay, a
            # report, a code snippet) are L1/L2 writing
            # requests, NOT keystroke dumps. Without this
            # cap, "write an IELTS essay about X" / "type a
            # 500-word summary" would be misrouted as
            # gui.type_text with multi-paragraph text.
            if len(payload) > 80:
                return None
            # Coding-task guard: "write python code for a
            # calculator" / "type a hello world script" /
            # "write a function to reverse a string" are
            # Level-2 Coding Agent tasks, NOT gui.type_text
            # requests. Without this guard the gui.type_text
            # pattern would steal compound
            # L2+L3 requests ("open notepad and write python
            # code for a calculator") by matching the second
            # clause as if it were literal text to type. We
            # only match gui.type_text for short, prose-shaped
            # payloads — anything that mentions a programming
            # concept or code artifact falls through to the
            # Coding Agent path.
            payload_lower = payload.lower()
            coding_signals = (
                "code", "script", "function", "program",
                "algorithm", "module", "class ", "method",
                "snippet", "lambda", "api", "endpoint",
                "regex", "compiler", "interpreter",
                "calculator", "fibonacci",
                "sorting", "quicksort", "binary search",
                "linked list", "tree traversal", "recursion",
                " for a ", " that ", " to compute ",
                " in python", " in javascript", " in js",
                " in c++", " in java", " in typescript",
            )
            if any(sig in payload_lower for sig in coding_signals):
                return None
            # Creative-writing guard: "write a poem" / "write a
            # story" / "write an essay" / "write a paragraph" /
            # "write a sentence" describe a creative-writing task
            # the user wants Genesis to author, NOT a string the
            # user wants Genesis to type into a focused window.
            # Without this guard the gui.type_text pattern would
            # misroute "open chrome and write a poem" as a
            # 2-step compound L3 objective instead of letting the
            # mixed-level orchestrator surface it as an L1/L2
            # creative-writing request.
            creative_signals = (
                "poem", "essay", "story", "paragraph",
                "sentence", "article", "blog post",
                "short story", "report",
            )
            stripped_payload = payload_lower.strip(" .,!?")
            if (
                stripped_payload in creative_signals
                or any(
                    stripped_payload.startswith(sig + " ")
                    or stripped_payload.startswith(sig + ".")
                    or stripped_payload.startswith("a " + sig)
                    or stripped_payload.startswith("an " + sig)
                    or stripped_payload.startswith("the " + sig)
                    for sig in creative_signals
                )
                or any(
                    "write a " + sig in stripped_payload
                    or "write an " + sig in stripped_payload
                    or "write the " + sig in stripped_payload
                    for sig in creative_signals
                )
            ):
                return None
            return self._decision(
                3, "os", text,
                (
                    f"Type '{payload}' into "
                    f"{target or 'the focused window'}."
                ),
                0.95,
                intent=intent,
                target=target,
                parameters={
                    "text": payload,
                    "target_window": target,
                    "confirmed": True,
                },
            )

        # -------------------------------------------------
        # SEMANTIC INTENT FALLBACK (LLM-based)
        # -------------------------------------------------
        # If deterministic patterns didn't match but the text
        # looks like it could be an OS command, try LLM-based
        # semantic understanding. This handles novel phrasings
        # that weren't anticipated in regex patterns.
        semantic = self._try_semantic_intent_resolution(text)
        if semantic is not None:
            return semantic

        return None

    def _resolve_with_capability_control_plane(
        self,
        decision: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(decision, dict):
            return None
        operation = decision.get("operation") or decision.get("intent")
        if not operation or operation in {"compound.os", "memory.store"}:
            return decision
        resolver = getattr(self, "capability_resolver", None)
        if resolver is None:
            return decision
        parameters = decision.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        resolution = resolver.resolve_operation(
            operation,
            description=str(decision.get("task", "")),
            inputs=parameters.keys(),
        )
        if not resolution.resolved:
            # MEASURED, NOT A SUSPECT: this discard path is
            # unreachable for every registered capability
            # (0/141 resolve non-RESOLVED), and 0/20 validated
            # semantic answers on the held-out dev set hit it. The
            # "round trip completed but no L3 decision" class in the
            # final3 taxonomy was therefore NOT answers deleted
            # here: those requests reached the model and it returned
            # no usable shortlist, which is the same failure mode the
            # 7B local model exhibited 61/61 times. The real
            # LLM-blocking defect was the looks_actionable cost gate,
            # which rejected requests before any call.
            return None
        from genesis_os.capability_resolution import (
            capability_resolution_metadata,
        )
        updated = dict(decision)
        updated["parameters"] = dict(parameters)
        updated["parameters"]["_capability_resolution"] = (
            capability_resolution_metadata(resolution)
        )
        return updated

    # =====================================================
    # SEMANTIC INTENT RESOLUTION (LLM Fallback)
    # =====================================================

    def _try_semantic_intent_resolution(
        self,
        text: str,
        prior_turn: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to resolve intent using semantic understanding
        via the Genesis AI engine (Level 1).

        This handles natural language that doesn't match any
        deterministic pattern but still represents a valid
        OS capability.
        """
        if not hasattr(self, '_llm_resolver') or self._llm_resolver is None:
            return None

        # Only try for actionable-looking requests
        if not self._looks_actionable_for_llm(text):
            return None

        try:
            # ITEM 4: passed only when supplied, so the no-prior call
            # is literally the pre-Item-4 call and any existing
            # override with the old signature keeps working.
            candidate = self._llm_resolver.resolve(
                text,
                **({"prior_turn": prior_turn} if prior_turn else {}),
            )
        except Exception:
            return None

        if candidate is None:
            return None

        # Validate the candidate through safety and registry
        operation = candidate.get("operation") or candidate.get("intent")
        if not operation:
            return None

        # Check if operation is registered and allowed
        try:
            from genesis_os.capability_registry import CapabilityRegistry
            from genesis_os.execution_safety import ExecutionSafety

            if not CapabilityRegistry.exists(operation):
                return None

            decision_check = ExecutionSafety.check(operation)
            if not decision_check.allowed:
                return None
        except Exception:
            return None

        # Extract target from candidate
        target = candidate.get("target")
        if not target:
            # Try to infer target from operation
            target = operation.split(".", 1)[0]

        parameters = candidate.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        parameters = dict(parameters)
        parameters["_semantic_resolution"] = True

        # Cap confidence for LLM-resolved intents
        confidence = min(
            float(candidate.get("confidence", 0.0)),
            0.85
        )

        decision = self._decision(
            level=3,
            mode="os",
            task=text,
            intent=operation,
            application=None,
            target=target,
            parameters=parameters,
            confidence=confidence,
            reason=(
                "Semantic interpretation via Genesis AI; "
                "confirmation recommended for novel phrasings."
            ),
        )
        return self._resolve_with_capability_control_plane(decision)

    def _looks_actionable_for_llm(self, text: str) -> bool:
        """
        Cheap gate to determine if a request looks like it
        could be an OS operation (worth sending to LLM).

        Delegates to LLMIntentResolver.looks_actionable for
        consistency — this gate must not have its own verb
        list that diverges from the canonical one.
        """
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        return LLMIntentResolver.looks_actionable(text)

    def _description_affinity(
        self,
        capability_id: str,
        text: str,
    ) -> float:
        """
        Fraction of a capability's description content words that
        appear in the request. 0.0 when the capability is unknown.

        This is the lexical evidence used to decide whether a
        deterministic match is contradicted by its own family. It
        is deliberately not a semantic score; it only has to
        answer "does some sibling in this family describe the
        request better than the capability that matched".
        """

        try:
            from genesis_os.capability_registry import (
                CapabilityRegistry,
            )
            description = CapabilityRegistry.get(
                capability_id
            ).description
        except Exception:
            return 0.0

        stop = {
            "the", "a", "an", "to", "into", "on", "in", "for",
            "and", "or", "my", "that", "this", "it", "with",
            "at", "of", "from", "please", "now", "me", "can",
            "you", "do",
        }
        words = {
            token
            for token in description.lower().replace(".", " ").split()
            if len(token) > 2 and token not in stop
        }
        if not words:
            return 0.0
        request = set(text.lower().split())
        return len(words & request) / len(words)

    def _deterministic_match_is_only_a_hint(
        self,
        decision: Optional[Dict[str, Any]],
        text: str = "",
    ) -> bool:
        """
        True when a deterministic L3 decision should be treated as a
        fast hint that the semantic layer may overrule.

        A match is only a hint when ALL of these hold:

          * it is a concrete capability id (contains a domain), and
          * it did NOT already come from the semantic resolver, and
          * nothing anchors it — no explicit target and no named
            application, so there is no concrete object the match
            was read off, and
          * its own capability family CONTRADICTS it: some sibling
            in the same domain describes the request strictly
            better than the capability that matched.

        That last clause is what makes the override safe. An
        earlier version treated every unanchored match as a hint
        and let the model answer unconditionally, which was
        measured to be harmful: "write hello world" correctly
        classified as gui.type_text by the deterministic layer was
        overwritten with document.create_txt by the model,
        breaking a pinned Phase 0 forensic regression guard.

        Overriding only on a CONTRADICTED family keeps the win that
        motivated the change — "go back to the previous track"
        hints media.play_pause while media.previous describes the
        request three times better (0.667 vs 0.000), so the hint is
        overruled — while never overruling a hint that is its own
        family's best lexical match.

        With no request text there is nothing to arbitrate, so the
        match is treated as a hint and the model is asked.
        """

        if not isinstance(decision, dict):
            return False

        intent = decision.get("intent")
        if not isinstance(intent, str) or "." not in intent:
            return False

        parameters = decision.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}

        # Already semantic — consulting again would loop.
        if parameters.get("_semantic_resolution"):
            return False

        # Anchored matches stay on the fast path.
        if decision.get("target") or decision.get("application"):
            return False

        domain = intent.split(".", 1)[0]

        try:
            from genesis_os.capability_registry import (
                CapabilityRegistry,
            )
            family = [
                capability.capability_id
                for capability in CapabilityRegistry.all()
                if capability.capability_id.split(".", 1)[0]
                == domain
            ]
        except Exception:
            return False

        if len(family) <= 1:
            return False

        if not text.strip():
            return True

        hint_affinity = self._description_affinity(intent, text)
        return any(
            self._description_affinity(sibling, text)
            > hint_affinity + 1e-9
            for sibling in family
            if sibling != intent
        )

    def _arbitrate_os_decision(
        self,
        text: str,
        decision: Optional[Dict[str, Any]],
        prior_turn: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Let a grounded semantic candidate challenge a deterministic
        one, across domains.

        GENERIC BY CONSTRUCTION
        -----------------------
        Nothing here knows any domain. The challenge is admissible
        whenever the request is lexically AMBIGUOUS (the tier that
        already means "the lexical layer cannot tell"), a grounded
        semantic candidate exists, and it names a different
        registered capability. Whether those two capabilities share a
        domain is decided by the comparison, not by a rule.

        COST
        ----
        A model call is made ONLY when all of these hold: a
        deterministic candidate exists, the request is lexically
        ambiguous, and the semantic probe actually grounds a
        different registered capability. The overwhelmingly common
        case -- a clear deterministic match on an unambiguous request
        -- pays nothing and returns immediately.

        Returns the chosen decision, or the original when nothing
        challenges it.
        """

        if not isinstance(decision, dict):
            return decision

        deterministic_capability = decision.get("intent")
        if not isinstance(deterministic_capability, str):
            return decision
        if "." not in deterministic_capability:
            return decision

        resolver = getattr(self, "_llm_resolver", None)
        if resolver is None:
            return decision

        try:
            from genesis_os.llm_intent_resolver import (
                LLMIntentResolver,
            )
        except Exception:
            return decision

# TRIGGER: is the deterministic candidate's evidence DECISIVE?
        #
        # This used to be a lexical proxy — "is the matched domain's
        # vocabulary absent from the request?" — and that was the
        # wrong question. Measured: a capability can be strongly
        # deterministic while the request says little in its
        # domain's vocabulary, and can carry plenty of that
        # vocabulary while being semantically ambiguous, so the two
        # cases are not the same and the proxy blocked the very
        # classes it should have caught.
        #
        # The decisive test now asks whether THIS request justifies
        # THIS capability: does it name a concrete target or
        # application, or does it literally name the operation the
        # capability performs? Both signals come from the
        # capability's own registry descriptor, so no domain is
        # named, no domain pair is special-cased, and no vocabulary
        # is introduced.
        #
        # A non-decisive candidate is a bare id with no per-request
        # justification, so a semantic challenge is warranted. A
        # decisive one pays nothing.
        try:
            eligibility = (
                LLMIntentResolver.deterministic_evidence_is_decisive(
                    text, decision, deterministic_capability
                )
            )
        except Exception:
            return decision

        if eligibility.get("decisive"):
            return decision

        parameters = dict(decision.get("parameters") or {})
        parameters["_arbitration_eligibility"] = {
            "decisive": False,
            "signals": eligibility.get("signals", {}),
            "reasons": list(eligibility.get("reasons", ())),
        }

        # Obtain a challenger through the SAME grounding contract the
        # previous task established. The deterministic-only tier
        # restriction is lifted here on purpose: arbitration is
        # precisely the case where the lexical tier is ambiguous, and
        # nothing else about the contract changes.
        try:
            # ITEM 4: the prior turn is passed ONLY when supplied, so
            # the no-prior call is literally the pre-Item-4 call. That
            # keeps the no-op guarantee true at the call boundary, and
            # keeps any existing override or test double that still has
            # the old signature working unchanged.
            #
            # Arbitration's OWN comparison probe (`arbitration_probe`)
            # is deliberately left prior-unaware in this item:
            # arbitration is done, and its anchor-fidelity rule was
            # specified for single-turn requests, so widening it is out
            # of scope here. Only the grounding call gains context.
            context = (
                {"prior_turn": prior_turn} if prior_turn else {}
            )
            grounding = resolver.grounded_capability(
                text,
                require_ambiguous_tier=False,
                **context,
            )
        except Exception:
            grounding = None

        if not grounding:
            return decision
        if grounding.capability_id == deterministic_capability:
            return decision

        try:
            arbitration = resolver.arbitrate_capabilities(
                text, decision, grounding
            )
        except Exception:
            return decision

        if "_arbitration_eligibility" not in parameters:
            parameters["_arbitration_eligibility"] = {
                "decisive": False,
                "signals": eligibility.get("signals", {}),
                "reasons": list(eligibility.get("reasons", ())),
            }
        parameters["_capability_arbitration"] = arbitration.to_dict()

        if arbitration.selected != "semantic":
            decision = dict(decision)
            decision["parameters"] = parameters
            return decision

        # Semantic candidate wins: rebuild the decision from it, then
        # pass it through the same control plane and promotion gate as
        # any other semantic decision.
        promoted = self._decision(
            level=3,
            mode="os",
            task=decision.get("task") or text,
            reason=(
                "Cross-domain capability arbitration selected the "
                "semantic candidate over the deterministic one."
            ),
            confidence=0.85,
            intent=grounding.capability_id,
            parameters={
                "_semantic_resolution": True,
                "_semantic_grounding": grounding.to_dict(),
            },
        )

        resolved = self._resolve_with_capability_control_plane(
            promoted
        )
        if not isinstance(resolved, dict):
            return decision
        resolved_parameters = dict(
            resolved.get("parameters") or {}
        )
        if resolved_parameters.get(
            "_capability_resolution"
        ) is None:
            return decision
        resolved_parameters["_capability_arbitration"] = (
            arbitration.to_dict()
        )
        resolved_parameters["_arbitration_eligibility"] = (
            parameters["_arbitration_eligibility"]
        )
        resolved["parameters"] = resolved_parameters
        return resolved

    def _grounded_os_decision(
        self,
        text: str,
        prior_turn: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Escalate a lexically AMBIGUOUS request to semantic grounding.

        Returns a Level 3 decision only when the semantic grounding
        contract is satisfied (see
        LLMIntentResolver.grounded_capability): the model committed
        to actionable, named a registered capability, quoted a
        verbatim span of the request, and that span carries a real
        content word. The decision is then passed through the
        existing control plane, so capability resolution metadata
        and the promotion rules are identical to every other
        semantic decision.

        Returns None for ordinary conversation, which is what keeps
        the false-positive protections intact without a keyword
        list: the model has to produce checkable evidence before an
        action exists.
        """

        resolver = getattr(self, "_llm_resolver", None)
        if resolver is None:
            return None

        try:
            from genesis_os.llm_intent_resolver import (
                LLMIntentResolver,
            )
        except Exception:
            return None

        # Only AMBIGUOUS text may be escalated. BLOCKED text is
        # never sent to the model, and ACTIONABLE text has already
        # had its chance on the normal semantic path above.
        try:
            tier = LLMIntentResolver.lexical_actionability(text)
        except Exception:
            return None

        if tier != LLMIntentResolver.AMBIGUOUS:
            return None

        try:
            grounded = resolver.grounded_capability(
                text,
                **({"prior_turn": prior_turn} if prior_turn else {}),
            )
        except Exception:
            return None

        if not grounded:
            return None

        decision = self._decision(
            level=3,
            mode="os",
            task=text,
            reason=(
                "Semantically grounded interpretation. The lexical "
                "layer could not classify this request, and the "
                "chosen capability is anchored in the user's own "
                f"words ({grounded.anchor!r})."
            ),
            confidence=0.85,
            intent=grounded.capability_id,
            parameters={
                "_semantic_resolution": True,
                "_semantic_grounding": grounded.to_dict(),
            },
        )

        # Same control plane every other semantic decision passes
        # through. It also stamps _capability_resolution, which is
        # what the promotion gate reads. Grounding already resolved
        # the capability once for its own evidence, so this is a
        # second, independent confirmation rather than new work.
        resolved = self._resolve_with_capability_control_plane(
            decision
        )

        if not isinstance(resolved, dict):
            return None
        if (resolved.get("parameters") or {}).get(
            "_capability_resolution"
        ) is None:
            return None

        return resolved

    def _semantic_fallback_for_guarded_text(
        self,
        text: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Offer conversational/question-shaped text to the semantic
        resolver instead of dropping it.

        MEASURED 2026-09-27: with qwen2.5:7b answering correctly
        ("what is playing right now" -> media.play_pause, 63s),
        only 2 of 40 held-out items ever reached Level 3. The
        correct answers were being produced and then discarded,
        because _is_conversational_or_educational() is a PREFIX
        blocklist: "what is playing right now" starts with
        "what is " and so was treated as a general-knowledge
        question, and the guard sits ABOVE the semantic fallback
        in both _detect_os_intent and _detect_extended_os_intent.

        That blocklist cannot be completed by adding exceptions:
        the same "what is " prefix covers both "what is biology"
        and a genuine question about the user's own machine.

        The distinction is already made elsewhere and more
        reliably. looks_actionable() passes the capability
        questions ("what is playing right now", "how do these two
        sheets stack up", "what is my disk usage") and blocks the
        knowledge questions ("what is the capital of france",
        "what is biology", "explain what a computer is"), so the
        LLM is never even asked about general knowledge.

        So the guard is demoted to what it is actually good for:
        keeping educational text away from the REGEX layer. The
        semantic resolver, which answers null for anything that is
        not a computer request, gets its chance. Cost is one extra
        LLM call for the small residue of question-shaped text
        that carries computer vocabulary.
        """

        try:
            return self._try_semantic_intent_resolution(text)
        except Exception:
            return None

    # =====================================================
    # APPLICATION ACTION DETECTION
    # =====================================================

    def _detect_application_action(
        self,
        text: str,
    ) -> Optional[str]:
        """
        Detect application-level OS actions.

        Supported commands:

            open chrome
            launch chrome
            start chrome
            please open chrome
            please launch google chrome
            could you start vscode
            i want you to open notepad

            close chrome
            quit vscode
            please quit vscode
            terminate chrome

            inspect chrome
            check chrome
            status of chrome
            is chrome running?
            chrome is running

        IMPORTANT:

            Generic language must NOT become an OS action.

        Examples that must remain non-OS:

            the topic is climate change
            the word count is 250
            what is an essay
            is this sentence correct
            write an essay
            check grammar
            check code
            run python
            start writing
            open topic
        """

        text = self._normalize_text(text)

        if not text:
            return None

        # -------------------------------------------------
        # SYSTEM SHUTDOWN SAFETY
        # -------------------------------------------------

        if self._contains_system_shutdown(text):
            return None

        # =================================================
        # OPEN / LAUNCH / START
        # =================================================

        open_actions = (
            "open",
            "launch",
            "start",
            "fire up",
            "bring up",
            "load",
        )

        for action in open_actions:

            if self._contains_action_command(
                text,
                action,
            ):
                return "open"

        # =================================================
        # CLOSE / QUIT / EXIT / TERMINATE
        # =================================================

        close_actions = (
            "close",
            "quit",
            "exit",
            "terminate",
            "shut",
        )

        for action in close_actions:

            if self._contains_action_command(
                text,
                action,
            ):
                return "close"

        # =================================================
        # EXPLICIT INSPECTION
        # =================================================

        inspect_actions = (
            "inspect",
            "check",
            "status of",
            "status for",
            "what is happening with",
            "what's happening with",
        )

        for action in inspect_actions:

            if self._contains_action_command(
                text,
                action,
            ):
                return "inspect"

        # =================================================
        # NATURAL APPLICATION STATUS
        # =================================================

        # Examples:
        #
        # is chrome running?
        # is chrome open?
        # is google chrome currently running?
        #
        # "is" alone is NEVER enough.

        status_match = re.fullmatch(
            r"is\s+(.+?)\s+"
            r"(?:currently\s+)?"
            r"(running|open)\??",
            text,
        )

        if status_match:

            application_text = (
                status_match.group(1).strip()
            )

            application = self._extract_application(
                application_text
            )

            if application is not None:
                return "inspect"

        # =================================================
        # REVERSE STATUS
        # =================================================

        # Examples:
        #
        # chrome is running
        # vscode is open
        # google chrome is currently running

        reverse_status_match = re.fullmatch(
            r"(.+?)\s+is\s+"
            r"(?:currently\s+)?"
            r"(running|open)\??",
            text,
        )

        if reverse_status_match:

            application_text = (
                reverse_status_match.group(1).strip()
            )

            application = self._extract_application(
                application_text
            )

            if application is not None:
                return "inspect"

        return None

    # =====================================================
    # ACTION COMMAND DETECTION
    # =====================================================

    def _contains_action_command(
        self,
        text: str,
        action: str,
    ) -> bool:
        """
        Determine whether a genuine OS action command
        exists in the request.

        Supported forms:

            open chrome
            launch google chrome
            start vscode

            please open chrome
            please launch google chrome
            please quit vscode

            could you open chrome
            can you launch vscode
            would you start notepad

            i want you to open chrome
            i need you to close vscode

            help me open chrome

        The action must occur as a command rather than
        merely appearing as an ordinary word.

        Application resolution is performed separately
        by _extract_application().
        """

        text = self._normalize_text(text)
        action = self._normalize_text(action)

        if not text or not action:
            return False

        # -------------------------------------------------
        # DIRECT COMMAND
        # -------------------------------------------------

        # Examples:
        #
        # open chrome
        # launch google chrome
        # quit vscode

        if re.match(
            rf"^{re.escape(action)}(?:\s+|$)",
            text,
        ):
            return True

        # -------------------------------------------------
        # NATURAL / POLITE PREFIXES
        # -------------------------------------------------

        prefixes = (
            "please",
            "could you",
            "can you",
            "would you",
            "will you",
            "i want you to",
            "i need you to",
            "i want to",
            "i need to",
            "help me",
        )

        for prefix in prefixes:

            pattern = (
                rf"^{re.escape(prefix)}"
                rf"\s+{re.escape(action)}"
                rf"(?:\s+|$)"
            )

            if re.match(
                pattern,
                text,
            ):
                return True

        return False

    # =====================================================
    # SYSTEM SHUTDOWN SAFETY
    # =====================================================

    @staticmethod
    def _contains_system_shutdown(
        text: str,
    ) -> bool:
        """
        Prevent system shutdown requests from being
        interpreted as application.close.
        """

        text = " ".join(
            str(text)
            .lower()
            .split()
        )

        shutdown_patterns = (
            "shut down the computer",
            "shutdown the computer",

            "shut down my computer",
            "shutdown my computer",

            "shut down windows",
            "shutdown windows",

            "turn off the computer",
            "turn off my computer",

            "power off the computer",
            "power off my computer",

            "turn off pc",
            "power off pc",

            "shutdown pc",
            "shut down pc",

            "shut down my pc",
            "shutdown my pc",

            "turn off my pc",
            "power off my pc",
        )

        return any(
            pattern in text
            for pattern in shutdown_patterns
        )

    # =====================================================
    # APPLICATION EXTRACTION
    # =====================================================

    def _extract_application(
        self,
        text: str,
    ) -> Optional[str]:
        """
        Resolve a user-facing application name into a
        canonical Genesis application identifier.

        Longest aliases are matched first.

        Examples:

            chrome
                → chrome

            google chrome
                → chrome

            visual studio code
                → vscode

            display settings
                → display_settings
        """

        if not text:
            return None

        normalized_text = self._normalize_text(
            text
        )

        if not normalized_text:
            return None

        # =================================================
        # APPLICATION ALIASES
        # =================================================

        aliases = {

            # =============================================
            # BROWSERS
            # =============================================

            "google chrome": "chrome",
            "chrome browser": "chrome",
            "chrome": "chrome",

            "microsoft edge": "edge",
            "edge browser": "edge",
            "edge": "edge",

            "mozilla firefox": "firefox",
            "firefox browser": "firefox",
            "firefox": "firefox",

            "brave browser": "brave",
            "brave": "brave",

            "opera browser": "opera",
            "opera": "opera",

            # =============================================
            # DEVELOPMENT
            # =============================================

            "visual studio code editor": "vscode",
            "visual studio code": "vscode",
            "vs code": "vscode",
            "vscode": "vscode",

            "visual studio": "visual_studio",

            "pycharm": "pycharm",

            "android studio": "android_studio",

            # =============================================
            # WINDOWS BASIC APPS
            # =============================================

            "windows notepad": "notepad",
            "notepad": "notepad",

            "microsoft paint": "paint",
            "ms paint": "paint",
            "paint": "paint",

            "windows calculator": "calculator",
            "calculator": "calculator",
            "calc": "calculator",

            "snipping tool": "snipping_tool",
            "snip tool": "snipping_tool",

            # =============================================
            # FILE MANAGEMENT
            # =============================================

            "windows file explorer": "file_explorer",
            "file explorer": "file_explorer",
            "windows explorer": "file_explorer",
            "explorer": "file_explorer",

            # =============================================
            # TERMINALS
            # =============================================

            "windows terminal": "terminal",
            "terminal": "terminal",

            "windows powershell": "powershell",
            "power shell": "powershell",
            "powershell": "powershell",

            "command prompt": "cmd",
            "cmd prompt": "cmd",
            "cmd": "cmd",

            # =============================================
            # WINDOWS UTILITIES
            # =============================================

            "task manager": "task_manager",
            "taskmgr": "task_manager",

            "control panel": "control_panel",
            "control": "control_panel",

            "registry editor": "registry_editor",
            "regedit": "registry_editor",

            "resource monitor": "resource_monitor",

            "system configuration": (
                "system_configuration"
            ),

            "msconfig": "system_configuration",

            # =============================================
            # MICROSOFT OFFICE
            # =============================================

            "microsoft word": "word",
            "word": "word",

            "microsoft excel": "excel",
            "excel": "excel",

            "microsoft powerpoint": "powerpoint",
            "powerpoint": "powerpoint",

            "microsoft outlook": "outlook",
            "outlook": "outlook",

            "microsoft onenote": "onenote",
            "onenote": "onenote",

            # =============================================
            # MEDIA / COMMUNICATION
            # =============================================

            "discord": "discord",
            "spotify": "spotify",

            "vlc media player": "vlc",
            "vlc": "vlc",

            "slack": "slack",
            "microsoft teams": "teams",
            "teams": "teams",
            "microsoft photos": "photos",
            "photos app": "photos",
            "photos": "photos",
            "windows clock": "clock",
            "clock": "clock",
            "alarms": "clock",
            "weather": "weather",
            "microsoft store": "store",
            "store": "store",
            "onedrive": "onedrive",
            "sticky notes": "sticky_notes",
            "stickynotes": "sticky_notes",
            "snip & sketch": "snip_sketch",
            "snip and sketch": "snip_sketch",

            # Microsoft Maps / Windows Maps. The standalone
            # noun "maps" is also a Google Maps site alias, so
            # the application-target priority gate (section 0
            # in _detect_extended_os_intent) must win over the
            # site alias when the verb is "open"/"launch".
            "microsoft maps": "maps",
            "windows maps": "maps",
            "bing maps": "maps",
            # Bare "maps" is ambiguous: it can mean the
            # Microsoft Maps app OR a generic request to
            # see maps (the website). The application-target
            # priority gate in _detect_extended_os_intent
            # checks the FULL text — when the text contains
            # a map-provider qualifier ("google maps",
            # "apple maps", "open street map"), the URL
            # wins; otherwise the app wins.
            "maps": "maps",

            # =============================================
            # WINDOWS SETTINGS
            # =============================================

            "windows settings": "settings",
            "system settings": "settings",
            "pc settings": "settings",
            "settings": "settings",

            # =============================================
            # WINDOWS SETTINGS SUBPAGES
            # =============================================

            "display settings": "display_settings",

            "sound settings": "sound_settings",
            "audio settings": "sound_settings",

            "network and internet settings": (
                "network_settings"
            ),

            "network settings": "network_settings",

            "wifi settings": "wifi_settings",
            "wi-fi settings": "wifi_settings",

            "bluetooth settings": (
                "bluetooth_settings"
            ),

            "personalization settings": (
                "personalization_settings"
            ),

            "apps settings": "apps_settings",
            "app settings": "apps_settings",
            "installed apps": "apps_settings",

            "windows update": "windows_update",
            "update settings": "windows_update",

            "privacy settings": "privacy_settings",

            "accounts settings": "accounts_settings",
            "account settings": "accounts_settings",

            "date and time settings": "time_settings",
            "time settings": "time_settings",

            "language settings": "language_settings",
            "region settings": "language_settings",

            "accessibility settings": (
                "accessibility_settings"
            ),

            "ease of access settings": (
                "accessibility_settings"
            ),

            # =============================================
            # WINDOWS SECURITY
            # =============================================

            "windows security": "windows_security",
            "windows defender": "windows_security",

            # =============================================
            # MICROSOFT STORE
            # =============================================

            "microsoft store": "microsoft_store",
            "windows store": "microsoft_store",

            # =============================================
            # XBOX
            # =============================================

            "xbox app": "xbox",
            "xbox": "xbox",
        }

        # =================================================
        # LONGEST MATCH FIRST
        # =================================================

        sorted_aliases = sorted(
            aliases.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )

        for alias, canonical in sorted_aliases:

            if self._contains_phrase(
                normalized_text,
                alias,
            ):
                return canonical

        # =================================================
        # FUTURE APPLICATION DISCOVERY
        # =================================================

        # ------------------------------------------------
        # TYPO-TOLERANT FUZZY MATCHING
        #
        # Real users type "chrom", "firefix", "vscod". When no
        # exact phrase matched, accept a CLOSE alias match so
        # imperfect input still resolves to the right
        # application instead of falling out of the OS.
        # ------------------------------------------------

        words = normalized_text.split()

        for word in words:
            if len(word) < 3 or word in (
                "open", "launch", "start", "close", "quit",
                "exit", "terminate", "inspect", "check",
                "please", "status", "running",
            ):
                continue

            close = get_close_matches(
                word,
                aliases.keys(),
                n=1,
                cutoff=0.84,
            )

            if close:
                return aliases[close[0]]

        return None

    # =====================================================
    # SAFE PHRASE MATCHING
    # =====================================================

    @staticmethod
    def _contains_phrase(
        text: str,
        phrase: str,
    ) -> bool:
        """
        Match a complete phrase.

        Prevents accidental substring matches.

        Example:

            code
                must NOT match
            codec
        """

        text = f" {text.strip()} "
        phrase = f" {phrase.strip()} "

        return phrase in text

    # =====================================================
    # LEVEL 2 — MULTI AGENT
    # =====================================================

    def _detect_multi_agents(
        self,
        text: str,
    ) -> List[str]:
        """
        Detect multiple specialized agents.
        """

        matches: List[str] = []

        agents = self._available_agents()

        keyword_map = {

            "research": [
                "research",
                "investigate",
                "find sources",
                "study sources",
                "deep research",
                "papers",
                "paper",
                "publications",
                "literature",
                "academic",
                "look up",
                "look for papers",
                "recent papers",
            ],

            "coding": [
                "code",
                "coding",
                "programming",
                "debug",
                "debugging",
                "python",
                "javascript",
                "java script",
                "typescript",
                "flask",
                "django",
                "sql",
                "bash",
                "shell script",
                "shell-script",
                "regular expression",
                "regex",
                "fibonacci",
                "function",
                "class ",
                "method ",
                "interface ",
                "script",
                "query",
                "algorithm",
                "recursion",
                "recursive",
                "compile",
                "syntax",
                "compile-time",
                "runtime",
            ],

            "study": [
                "study",
                "learn",
                "explain lesson",
                "exam",
                "homework",
                "assignment",
            ],

            "internet": [
                "search internet",
                "search web",
                "browse web",
                "web search",
            ],

            "document": [
                "document",
                "pdf",
                "report",
                "write document",
                "create a document",
                "create a summary",
                "write a summary",
                "summarize",
                "summarise",
                "summary",
            ],

            "design": [
                "design",
                "ui",
                "ux",
                "graphic",
                "interface",
            ],

            "business": [
                "business",
                "marketing",
                "sales",
                "customer",
                "market",
                "market analysis",
                "startup",
                "company",
                "revenue",
                "profit",
                "business plan",
                "business strategy",
                "coffee shop",
            ],

            "data": [
                "data analysis",
                "analyze data",
                "analyze the data",
                "analyze this spreadsheet",
                "analyze this csv",
                "analyze this dataset",
                "analyze the spreadsheet",
                "analyse",
                "dataset",
                "statistics",
                "statistical",
                "outliers",
                "correlations",
                "correlation",
                "variance",
                "mean and standard deviation",
                "standard deviation",
                "compute the variance",
                "compute the mean",
                "compute the standard deviation",
                "compute the median",
                "give me a quick statistical summary",
                "statistical summary",
                "spreadsheet analysis",
                "data summary",
                "outlier",
                "compare these",
                "compare the two",
                "compare my",
                "spreadsheets",
                "this spreadsheet",
                "this csv",
            ],

            "planning": [
                "plan",
                "planning",
                "roadmap",
                "schedule",
            ],

            "security": [
                "security",
                "secure",
                "vulnerability",
                "cybersecurity",
            ],
        }

        for agent in agents:

            agent_name = self._agent_name(
                agent
            )

            if not agent_name:
                continue

            normalized_name = (
                agent_name
                .lower()
                .replace(" agent", "")
                .strip()
            )

            keywords = keyword_map.get(
                normalized_name,
                [normalized_name],
            )

            for keyword in keywords:

                # ITEM 18B (L17): word-boundary match, never a
                # raw substring — "ui" must not fire inside
                # "build"/"circuit"/"guide"/"quick".
                if _keyword_pattern(keyword).search(text):

                    if agent_name not in matches:
                        matches.append(
                            agent_name
                        )

                    break

        return matches

    # =====================================================
    # LEVEL 2 — SINGLE AGENT
    # =====================================================

    def _detect_single_agent(
        self,
        text: str,
    ) -> Optional[str]:
        """
        Detect one specialized agent.
        """

        agents = self._detect_multi_agents(
            text
        )

        if len(agents) == 1:
            return agents[0]

        return None

    # =====================================================
    # AVAILABLE AGENTS
    # =====================================================

    def _available_agents(
        self,
    ) -> List[Any]:
        """
        Safely retrieve registered agents.
        """

        if self.registry is None:
            return []

        try:

            if hasattr(
                self.registry,
                "get_all_agents",
            ):
                return list(
                    self.registry.get_all_agents()
                )

        except Exception:
            pass

        return []

    # =====================================================
    # AGENT NAME
    # =====================================================

    @staticmethod
    def _agent_name(
        agent,
    ) -> Optional[str]:
        """
        Safely obtain an agent name.
        """

        if agent is None:
            return None

        if isinstance(
            agent,
            str,
        ):
            return agent

        name = getattr(
            agent,
            "name",
            None,
        )

        if name:
            return str(name)

        return None

    # =====================================================
    # DEBUG / EXPLAIN
    # =====================================================

    def explain(
        self,
        text: str,
    ) -> Dict[str, Any]:
        """
        Return routing information in an explainable form.

        This prepares Genesis for the future
        Explainable Trust Layer.
        """

        decision = self.decide(
            text
        )

        return {
            "input": text,
            "decision": decision,
            "engine": "WorkflowDecisionEngine",
            "version": self.VERSION,
        }