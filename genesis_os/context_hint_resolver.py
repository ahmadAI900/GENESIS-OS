"""
Genesis OS — Level 3.19 Context Hint Resolver.

Architectural role
------------------
In a compound natural-language request such as

    "open settings and turn on bluetooth"

the second clause ("turn on bluetooth") is NOT independently
executable as a Level-3 OS intent: the decision engine does
not know which app's bluetooth setting the user means. The
meaning only becomes clear in the context of the first
clause ("open settings" -> system.open_settings target=settings).

This module provides a structured, meaning-based resolver
that, given a resolved 1st-clause decision and a raw 2nd-
clause fragment, produces a re-resolved 2nd-clause decision
when a meaning-based mapping exists.

The resolver is NOT a text rewriter. It does NOT prepend
"in settings, " to the 2nd clause and re-feed the text to
the decision engine. That approach does not work because the
decision engine's OS intent patterns are anchored on the
SURFACE form of the verb and noun, not on a contextual
preamble.

Instead, the resolver is a STRUCTURED LOOKUP that maps
    (first_clause_context_category, second_clause_noun)
to a Level-3 OS intent + parameters. The categories are
MEANING-BASED (settings sub-page catalog, app sub-action
catalog, etc.), not hard-coded sentences.

Why this is an architectural fix
--------------------------------
The naive alternative would be to extend the decision
engine's regex pattern library with one new pattern per
observed compound phrasing. That is a list of sentences,
not a generalisation.

The resolver, by contrast, is a SMALL number of MEANING
CATEGORIES (settings sub-pages, app-context actions) and
a LOOKUP TABLE from (category, noun) to (intent, params).
New unseen sub-pages are added by extending the catalog;
the resolver itself is unchanged.

The catalog is intentionally built FROM the existing
ms-settings: URI catalog in
genesis_os/applications/app_manager.py so the resolver
stays in lock-step with the real Windows Settings pages
the executor already knows how to open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# =====================================================================
# DATA MODEL
# =====================================================================


@dataclass(frozen=True)
class ContextHint:
    """Structured context carried from a 1st-clause decision
    to a 2nd-clause resolution attempt.

    A ContextHint is a *meaning*, not text. The resolver uses
    the category to choose which catalog to look the 2nd
    clause's noun up in.
    """

    category: str  # e.g. "settings_app", "browser_app", "file_manager"
    primary_target: Optional[str] = None
    primary_intent: Optional[str] = None
    primary_application: Optional[str] = None
    sub_page: Optional[str] = None  # for nested contexts
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextResolution:
    """Result of an attempt to resolve a 2nd clause with context.

    ``resolved`` is True iff the resolver found a (category,
    noun) -> intent mapping. ``decision`` is the resolved
    decision dict ready to be merged into the 2nd clause's
    ObjectiveStepIntent.
    """

    resolved: bool
    decision: Dict[str, Any]
    description: str
    family: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved": self.resolved,
            "decision": dict(self.decision),
            "description": self.description,
            "family": self.family,
        }


# =====================================================================
# SETTINGS SUB-PAGE CATALOG
# =====================================================================
#
# Each entry maps a MEANING CATEGORY (settings sub-page) to:
#   * a canonical sub-page name (matches the ms-settings: URI
#     tail used by the existing system.open_settings capability),
#   * the verb triggers that, when present in the 2nd clause,
#     indicate the user is asking to navigate to this sub-page
#     (turn on / switch on / enable / disable / configure / etc.).
#
# The catalog is MEANING-BASED: each entry is a sub-page of the
# real Windows Settings app, not a list of phrasings. New
# sub-pages can be added without changing the resolver.
#
# The catalog is intentionally read-only at runtime; tests
# may import it to assert coverage.

SETTINGS_SUB_PAGES: Dict[str, Dict[str, Any]] = {
    # Canonical sub-page name -> {
    #     "uri_tail": ms-settings: URI fragment,
    #     "display": human-readable name,
    #     "triggers": verbs / nouns that indicate this sub-page,
    # }
    "bluetooth": {
        "uri_tail": "bluetooth",
        "display": "Bluetooth & devices",
        "triggers": frozenset({
            "bluetooth", "airpods", "headphones", "speaker", "speakers",
            "wireless", "pair", "paired", "pairing",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "activate", "deactivate",
            "power on", "power off", "toggle", "connect", "disconnect",
        }),
    },
    "network-wifi": {
        "uri_tail": "network-wifi",
        "display": "Wi-Fi",
        "triggers": frozenset({
            "wifi", "wi-fi", "wi fi", "wireless network", "wireless",
            "hotspot", "ssid", "home network", "office network",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "connect", "disconnect", "join",
        }),
    },
    "network": {
        "uri_tail": "network",
        "display": "Network & internet",
        "triggers": frozenset({
            "network", "ethernet", "vpn", "proxy", "dns",
        }),
        "toggle_verbs": frozenset({
            "configure", "set up", "open", "show",
        }),
    },
    "display": {
        "uri_tail": "display",
        "display": "Display",
        "triggers": frozenset({
            "display", "screen", "resolution", "brightness",
            "night light", "nightlight", "dark mode", "color",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "activate", "deactivate",
            "configure", "set", "change", "adjust",
        }),
    },
    "personalization": {
        "uri_tail": "personalization",
        "display": "Personalization",
        "triggers": frozenset({
            "personalization", "theme", "wallpaper", "background",
            "accent", "color", "lock screen", "taskbar",
            "dark mode", "light mode", "appearance",
        }),
        "toggle_verbs": frozenset({
            "change", "set", "configure", "turn on", "turn off",
            "switch on", "switch off", "enable", "disable",
        }),
    },
    "sound": {
        "uri_tail": "sound",
        "display": "Sound",
        "triggers": frozenset({
            "sound", "audio", "volume", "speaker", "speakers",
            "headphones", "microphone", "mic", "output",
            "input device", "playback", "recording",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "mute", "unmute",
            "configure", "set", "change", "switch",
        }),
    },
    "notifications": {
        "uri_tail": "notifications",
        "display": "Notifications",
        "triggers": frozenset({
            "notification", "notifications", "alert", "alerts",
            "toast", "toasts", "banner", "banners",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "mute", "unmute",
            "configure", "set", "change",
        }),
    },
    "privacy": {
        "uri_tail": "privacy",
        "display": "Privacy",
        "triggers": frozenset({
            "privacy", "permissions", "camera", "microphone",
            "location", "tracking", "telemetry", "diagnostics",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "configure", "set", "change",
        }),
    },
    "appsfeatures": {
        "uri_tail": "appsfeatures",
        "display": "Apps",
        "triggers": frozenset({
            "apps", "app", "applications", "installed", "uninstall",
            "default apps", "startup",
        }),
        "toggle_verbs": frozenset({
            "uninstall", "remove", "configure", "set", "change",
            "reset", "repair", "modify",
        }),
    },
    "windowsupdate": {
        "uri_tail": "windowsupdate",
        "display": "Windows Update",
        "triggers": frozenset({
            "windows update", "update", "updates", "patch",
            "patches", "upgrade",
        }),
        "toggle_verbs": frozenset({
            "check", "install", "download", "pause", "resume",
            "configure", "set", "change",
        }),
    },
    "accounts": {
        "uri_tail": "accounts",
        "display": "Accounts",
        "triggers": frozenset({
            "account", "accounts", "user", "users", "profile",
            "sign-in", "sign in", "password", "login",
        }),
        "toggle_verbs": frozenset({
            "configure", "set", "change", "add", "remove",
            "sign in", "sign out",
        }),
    },
    "dateandtime": {
        "uri_tail": "dateandtime",
        "display": "Time & language",
        "triggers": frozenset({
            "time", "date", "timezone", "time zone", "clock",
            "language", "region", "keyboard",
        }),
        "toggle_verbs": frozenset({
            "set", "change", "configure", "switch", "adjust",
        }),
    },
    "regionlanguage": {
        "uri_tail": "regionlanguage",
        "display": "Language",
        "triggers": frozenset({
            "language", "languages", "region", "locale",
            "keyboard layout", "input method",
        }),
        "toggle_verbs": frozenset({
            "set", "change", "configure", "switch", "add",
        }),
    },
    "easeofaccess": {
        "uri_tail": "easeofaccess",
        "display": "Accessibility",
        "triggers": frozenset({
            "accessibility", "ease of access", "high contrast",
            "narrator", "magnifier", "captions", "sticky keys",
        }),
        "toggle_verbs": frozenset({
            "turn on", "turn off", "switch on", "switch off",
            "enable", "disable", "activate", "deactivate",
            "configure", "set", "change",
        }),
    },
    "storage": {
        "uri_tail": "storage",
        "display": "Storage",
        "triggers": frozenset({
            "storage", "disk", "drive", "space", "cleanup",
            "memory usage", "disk usage",
        }),
        "toggle_verbs": frozenset({
            "configure", "set", "change", "free up", "clean",
        }),
    },
}


# =====================================================================
# APP-CREATE-DOCUMENT CONSTANTS (Level 3.20)
# =====================================================================
# Defined BEFORE build_context_hint so the context hint can
# recognise apps that can create documents.

_APP_DOCUMENT_CAPABILITIES = {
    # app name (lowercased) -> {
    #   "document_kinds": set of nouns that trigger this app,
    #   "intent": the document.create_* capability to use,
    #   "app_label": human-readable app name,
    # }
    "word": {
        "document_kinds": frozenset({
            "document", "doc", "letter", "report",
            "memo", "essay", "article",
        }),
        "intent": "document.create_docx",
        "app_label": "Word",
    },
    "microsoft word": {
        "document_kinds": frozenset({
            "document", "doc", "letter", "report",
            "memo", "essay", "article",
        }),
        "intent": "document.create_docx",
        "app_label": "Word",
    },
    "excel": {
        "document_kinds": frozenset({
            "spreadsheet", "sheet", "workbook", "budget",
            "ledger", "table",
        }),
        "intent": "document.create_csv",
        "app_label": "Excel",
    },
    "microsoft excel": {
        "document_kinds": frozenset({
            "spreadsheet", "sheet", "workbook", "budget",
            "ledger", "table",
        }),
        "intent": "document.create_csv",
        "app_label": "Excel",
    },
    "powerpoint": {
        "document_kinds": frozenset({
            "presentation", "deck", "slides", "slide",
        }),
        "intent": "document.create_docx",
        "app_label": "PowerPoint",
    },
    "microsoft powerpoint": {
        "document_kinds": frozenset({
            "presentation", "deck", "slides", "slide",
        }),
        "intent": "document.create_docx",
        "app_label": "PowerPoint",
    },
    "notepad": {
        "document_kinds": frozenset({
            "file", "text file", "note", "document",
            "doc",
        }),
        "intent": "document.create_txt",
        "app_label": "Notepad",
    },
    "notepad++": {
        "document_kinds": frozenset({
            "file", "text file", "note", "document",
            "doc", "source file", "script",
        }),
        "intent": "document.create_txt",
        "app_label": "Notepad++",
    },
    "vscode": {
        "document_kinds": frozenset({
            "file", "text file", "note", "document",
            "doc", "source file", "script", "code file",
        }),
        "intent": "document.create_txt",
        "app_label": "VS Code",
    },
    "visual studio code": {
        "document_kinds": frozenset({
            "file", "text file", "note", "document",
            "doc", "source file", "script", "code file",
        }),
        "intent": "document.create_txt",
        "app_label": "VS Code",
    },
    "sublime": {
        "document_kinds": frozenset({
            "file", "text file", "note", "document",
            "source file", "script",
        }),
        "intent": "document.create_txt",
        "app_label": "Sublime Text",
    },
    "notepadqq": {
        "document_kinds": frozenset({
            "file", "text file", "note", "document",
        }),
        "intent": "document.create_txt",
        "app_label": "Notepadqq",
    },
}


# =====================================================================
# CONTEXT EXTRACTION
# =====================================================================


def build_context_hint(
    first_clause_decision: Dict[str, Any],
) -> Optional[ContextHint]:
    """Build a structured ContextHint from a 1st-clause
    decision. Returns None when the 1st clause does not
    represent a known context category.
    """

    if not isinstance(first_clause_decision, dict):
        return None

    level = first_clause_decision.get("level")
    mode = first_clause_decision.get("mode")
    if level != 3 or mode != "os":
        return None

    intent = first_clause_decision.get("intent") or first_clause_decision.get("operation")
    target = first_clause_decision.get("target")
    application = first_clause_decision.get("application")

    # ----- settings_app context -----
    if intent == "system.open_settings":
        sub_page = target if isinstance(target, str) else None
        return ContextHint(
            category="settings_app",
            primary_target=target,
            primary_intent=intent,
            sub_page=sub_page,
        )

    # ----- settings_app context (via application.open of the
    #       Settings app) -----
    if intent == "application.open":
        app = (application or target or "")
        if isinstance(app, str) and _is_settings_name(app):
            # Determine the sub-page from the target name.
            sub_page = _settings_sub_page_from_noun(
                _extract_noun_phrase(str(target or app))
            )
            return ContextHint(
                category="settings_app",
                primary_target=app,
                primary_intent=intent,
                primary_application=app,
                sub_page=sub_page,
            )

    # ----- browser_app context -----
    if intent == "application.open":
        app = (application or target or "")
        if isinstance(app, str) and _is_browser_name(app):
            return ContextHint(
                category="browser_app",
                primary_target=app,
                primary_intent=intent,
                primary_application=app,
            )

    # ----- file_manager context -----
    if intent == "application.open":
        app = (application or target or "")
        if isinstance(app, str) and _is_file_manager_name(app):
            return ContextHint(
                category="file_manager",
                primary_target=app,
                primary_intent=intent,
                primary_application=app,
            )

    # ----- app_with_documents context (Level 3.20) -----
    # When the 1st clause opens an app that can create
    # documents (word, excel, powerpoint, notepad, IDEs,
    # text editors), the context category is
    # app_with_documents. The _app_create_document_resolution
    # function uses this category together with the app name
    # to map a 2nd clause's "create/start/write" + document
    # noun to the right document.create_* capability.
    if intent == "application.open":
        app = (application or target or "")
        if isinstance(app, str):
            app_key = app.lower().strip()
            # We check the app against the document-capable
            # app registry lazily here to avoid an import
            # cycle. The registry is defined in this same
            # module above the resolver functions.
            if _APP_DOCUMENT_CAPABILITIES and app_key in _APP_DOCUMENT_CAPABILITIES:
                return ContextHint(
                    category="app_with_documents",
                    primary_target=app,
                    primary_intent=intent,
                    primary_application=app,
                    sub_page=app_key,
                )

    # ----- file_manager context (via file.open of a file
    #       manager). The existing decision engine routes
    #       "open the file manager" to file.open with
    #       source_is_anaphoric=True and target=None. The
    #       context resolver recognises the file manager
    #       from the original fragment text (carried in the
    #       _original_fragment field) or from the target
    #       name itself. -----
    if intent == "file.open":
        params = first_clause_decision.get("parameters") or {}
        description = params.get("description") or ""
        original_fragment = first_clause_decision.get(
            "_original_fragment"
        ) or ""
        # Try to extract a file manager name from the
        # target, then description, then original fragment.
        # Each candidate is run through a noun-extraction
        # so leading verb prefixes ("open the") do not
        # prevent the match.
        for candidate in (target, description, original_fragment):
            if not (isinstance(candidate, str) and candidate.strip()):
                continue
            # Direct match.
            if _is_file_manager_name(candidate):
                return ContextHint(
                    category="file_manager",
                    primary_target=candidate,
                    primary_intent=intent,
                    primary_application=None,
                )
            # Noun-extracted match.
            noun = _extract_noun_phrase(candidate)
            if noun and _is_file_manager_name(noun):
                return ContextHint(
                    category="file_manager",
                    primary_target=noun,
                    primary_intent=intent,
                    primary_application=None,
                )

    return None


_BROWSER_NAMES = frozenset({
    "chrome", "google chrome", "firefox", "mozilla firefox",
    "edge", "microsoft edge", "safari", "opera", "brave",
    "vivaldi", "chromium", "internet explorer", "ie",
    "browser", "web browser",
})

_FILE_MANAGER_NAMES = frozenset({
    "file manager", "file explorer", "explorer", "finder",
    "files", "file browser", "windows explorer", "nautilus",
    "files app",
})

# Settings app aliases. When the 1st clause opens one of
# these, the context is the settings app regardless of
# whether the decision engine classified the intent as
# application.open (Settings is a real Windows app) or
# system.open_settings (the canonical settings page).
_SETTINGS_APP_NAMES = frozenset({
    "settings", "windows settings", "system settings",
    "pc settings", "control panel",
})

# Settings sub-page names that, when used as the 1st
# clause's target, also indicate the settings context.
_SETTINGS_SUB_PAGE_NAMES = frozenset({
    "bluetooth", "bluetooth_settings",
    "wifi", "wi-fi", "wifi_settings", "network", "network-wifi",
    "network_settings",
    "display", "display_settings",
    "personalization", "personalization_settings",
    "sound", "sound_settings", "audio", "audio_settings",
    "notifications", "notification",
    "privacy", "privacy_settings",
    "apps", "apps_settings", "app settings",
    "windows update", "windows_update", "update",
    "accounts", "account", "accounts_settings",
    "time", "dateandtime", "time_settings",
    "language", "regionlanguage", "language_settings",
    "accessibility", "easeofaccess", "accessibility_settings",
    "storage", "storage_settings",
})


def _is_browser_name(name: str) -> bool:
    n = name.lower().strip()
    if n in _BROWSER_NAMES:
        return True
    # Compound names like "Google Chrome" should still match.
    parts = n.split()
    if any(part in _BROWSER_NAMES for part in parts):
        return True
    return False


def _is_file_manager_name(name: str) -> bool:
    n = name.lower().strip()
    if n in _FILE_MANAGER_NAMES:
        return True
    parts = n.split()
    return any(part in _FILE_MANAGER_NAMES for part in parts)


def _is_settings_name(name: str) -> bool:
    """True when the given name is a settings-app or
    settings-sub-page identifier."""
    n = name.lower().strip()
    if n in _SETTINGS_APP_NAMES or n in _SETTINGS_SUB_PAGE_NAMES:
        return True
    # "the display settings" -> "display_settings" / "display"
    compact = n.replace("the ", "").replace(" my ", " ").strip()
    if compact in _SETTINGS_APP_NAMES or compact in _SETTINGS_SUB_PAGE_NAMES:
        return True
    parts = compact.split()
    return any(
        part in _SETTINGS_APP_NAMES or part in _SETTINGS_SUB_PAGE_NAMES
        for part in parts
    )


# =====================================================================
# SETTINGS CONTEXT RESOLUTION
# =====================================================================


def _extract_noun_phrase(text: str) -> str:
    """Extract the most likely noun phrase from a 2nd clause.

    Heuristic: drop leading verb/auxiliary tokens, keep the
    trailing noun phrase. Returns the lowered text minus
    common verb forms.
    """
    lowered = text.lower().strip()
    # Strip leading politeness markers
    lowered = re.sub(
        r"^(?:please\s+|kindly\s+|can\s+you\s+|could\s+you\s+|"
        r"would\s+you\s+|i\s+want\s+(?:to\s+)?|i\s+need\s+(?:to\s+)?|"
        r"i'd\s+like\s+to\s+|let's\s+)?",
        "",
        lowered,
    ).strip()

    # Drop leading common auxiliary/verb forms
    aux_patterns = [
        r"^(?:turn|switch|enable|disable|activate|deactivate|"
        r"power|connect|disconnect|toggle|configure|set|change|"
        r"adjust|modify|open|show|view|see|check|launch|start|"
        r"stop|reset|repair|uninstall|install|remove|add|join)\s+",
        r"^(?:on|off|to|the|a|an|my|that|this|those|these)\s+",
    ]
    changed = True
    while changed:
        changed = False
        for pat in aux_patterns:
            new_lowered, n = re.subn(pat, "", lowered, count=1)
            if n > 0:
                lowered = new_lowered
                changed = True

    return lowered.strip(" .?!,:;")


def _settings_sub_page_from_noun(noun: str) -> Optional[str]:
    """Given the noun phrase of a 2nd clause, return the
    matching settings sub-page canonical name, or None.

    Matching is MEANING-BASED: the catalog entries carry
    trigger noun sets, and the 2nd-clause noun is matched
    against those sets. Longer matches win (so "night light"
    beats "light" if both were triggers).
    """
    if not noun:
        return None

    noun_tokens = set(re.findall(r"[a-z][a-z\-]+", noun.lower()))

    best: Optional[Tuple[int, str]] = None
    for sub_page, info in SETTINGS_SUB_PAGES.items():
        triggers: FrozenSet[str] = info["triggers"]
        # Direct multi-word trigger match wins first.
        for trigger in triggers:
            if " " in trigger and trigger in noun.lower():
                score = len(trigger.split()) * 10
                if best is None or score > best[0]:
                    best = (score, sub_page)
                continue
        # Single-word trigger match by token intersection.
        for trigger in triggers:
            if " " in trigger:
                continue
            if trigger in noun_tokens:
                score = 1
                if best is None or score > best[0]:
                    best = (score, sub_page)

    return best[1] if best else None


def _settings_resolution(
    hint: ContextHint, fragment: str,
    current_decision: Optional[Dict[str, Any]] = None,
) -> Optional[ContextResolution]:
    """Attempt to resolve a 2nd clause as a settings sub-page
    navigation when the 1st clause was system.open_settings.
    """
    if hint.category != "settings_app":
        return None

    noun = _extract_noun_phrase(fragment)
    sub_page = _settings_sub_page_from_noun(noun)
    if not sub_page:
        return None

    sub_page_info = SETTINGS_SUB_PAGES[sub_page]
    return ContextResolution(
        resolved=True,
        decision={
            "level": 3,
            "mode": "os",
            "intent": "system.open_settings",
            "operation": "system.open_settings",
            "target": sub_page,
            "application": None,
            "parameters": {
                "settings": sub_page_info["uri_tail"],
                "sub_page": sub_page,
                "context_carried_from_first_clause": (
                    hint.primary_target
                ),
                "original_fragment": fragment,
            },
            "confidence": 0.91,
            "reason": (
                "Context-resolved: the user is already in the "
                "settings app (from the 1st clause) and the "
                "2nd clause names a settings sub-page."
            ),
        },
        description=(
            f"Open the {sub_page_info['display']} settings page "
            f"({sub_page_info['uri_tail']}) as the 2nd step of "
            f"the compound task."
        ),
        family="settings_sub_page",
    )


# =====================================================================
# BROWSER CONTEXT RESOLUTION
# =====================================================================


_BROWSER_GO_RE = re.compile(
    r"^(?:please\s+)?(?:"
    r"go\s+to|navigate\s+to|head\s+(?:over\s+)?to|visit|"
    r"browse\s+to|jump\s+to|open|load|"
    r"pull\s+up|fire\s+up)\s+(?:the\s+|my\s+)?(.+?)$",
    re.IGNORECASE,
)

_BROWSER_SEARCH_RE = re.compile(
    r"^(?:please\s+)?(?:search\s+(?:for|up)?|look\s+(?:for|up)|"
    r"find|hunt\s+for|seek|google|bing)\s+(.+?)$",
    re.IGNORECASE,
)


def _looks_like_url(text: str) -> bool:
    t = text.lower().strip()
    return (
        t.startswith("http://")
        or t.startswith("https://")
        or t.startswith("www.")
        or ("." in t and " " not in t and len(t) <= 60)
    )


def _browser_resolution(
    hint: ContextHint, fragment: str,
    current_decision: Optional[Dict[str, Any]] = None,
) -> Optional[ContextResolution]:
    """Attempt to resolve a 2nd clause as a browser navigation
    or search when the 1st clause opened a browser.

    ``current_decision`` is the standalone 2nd-clause
    decision. When the 2nd clause is already a non-browser
    L3 intent (e.g. file.search) the context override still
    fires, because a user who just opened a browser and then
    says "search for X" almost always means a web search.
    """

    if hint.category != "browser_app":
        return None

    stripped = fragment.strip()
    if not stripped:
        return None

    m = _BROWSER_SEARCH_RE.match(stripped)
    if m:
        query = m.group(1).strip().rstrip(".?!")
        if query and len(query) >= 2:
            return ContextResolution(
                resolved=True,
                decision={
                    "level": 3,
                    "mode": "os",
                    "intent": "browser.search",
                    "operation": "browser.search",
                    "target": query,
                    "application": hint.primary_application,
                    "parameters": {
                        "query": query,
                        "engine": "google",
                        "context_carried_from_first_clause": (
                            hint.primary_application
                        ),
                        "original_fragment": fragment,
                    },
                    "confidence": 0.93,
                    "reason": (
                        "Context-resolved: the user already "
                        "opened a browser (from the 1st clause) "
                        "and the 2nd clause is a search."
                    ),
                },
                description=(
                    f"Search the web for '{query}' in the "
                    f"browser opened by the 1st clause."
                ),
                family="browser_search",
            )

    m = _BROWSER_GO_RE.match(stripped)
    if m:
        destination = m.group(1).strip().rstrip(".?!")
        if not destination:
            return None
        if _looks_like_url(destination):
            url = destination
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            return ContextResolution(
                resolved=True,
                decision={
                    "level": 3,
                    "mode": "os",
                    "intent": "browser.open_url",
                    "operation": "browser.open_url",
                    "target": url,
                    "application": hint.primary_application,
                    "parameters": {
                        "url": url,
                        "context_carried_from_first_clause": (
                            hint.primary_application
                        ),
                        "original_fragment": fragment,
                    },
                    "confidence": 0.93,
                    "reason": (
                        "Context-resolved: the user already "
                        "opened a browser (from the 1st clause) "
                        "and the 2nd clause names a URL."
                    ),
                },
                description=(
                    f"Navigate the browser opened by the 1st "
                    f"clause to {url}."
                ),
                family="browser_navigate",
            )
        # Not a URL — resolve as a search instead.
        return ContextResolution(
            resolved=True,
            decision={
                "level": 3,
                "mode": "os",
                "intent": "browser.search",
                "operation": "browser.search",
                "target": destination,
                "application": hint.primary_application,
                "parameters": {
                    "query": destination,
                    "engine": "google",
                    "context_carried_from_first_clause": (
                        hint.primary_application
                    ),
                    "original_fragment": fragment,
                },
                "confidence": 0.90,
                "reason": (
                    "Context-resolved: the user already opened a "
                    "browser (from the 1st clause) and the 2nd "
                    "clause names a destination that is not a "
                    "URL; treated as a web search."
                ),
            },
            description=(
                f"Search the web for '{destination}' in the "
                f"browser opened by the 1st clause."
            ),
            family="browser_navigate_as_search",
        )

    return None


# =====================================================================
# FILE-MANAGER CONTEXT RESOLUTION
# =====================================================================


def _file_manager_resolution(
    hint: ContextHint, fragment: str,
    current_decision: Optional[Dict[str, Any]] = None,
) -> Optional[ContextResolution]:
    """Attempt to resolve a 2nd clause as a folder or
    file-system operation when the 1st clause opened a file
    manager.

    The file manager context enables a specific set of
    MEANING-BASED operations that are natural in a file
    manager: open a folder, create a folder, open the
    current folder, navigate home, navigate up. These are
    the operations that are genuinely context-dependent on
    being inside a file manager.

    File operations on specific files (rename, copy, delete)
    are NOT context-resolved here: they require a resolvable
    file target, which is a separate anaphoric-resolution
    capability (Level 3.16). The file manager context
    provides a hint about WHERE the file might be but
    cannot identify WHICH file the user means.
    """

    if hint.category != "file_manager":
        return None

    lowered = fragment.lower().strip()

    # ---- open folder: "open the downloads folder" ----
    m = re.match(
        r"^(?:please\s+)?open\s+(?:the\s+|my\s+)?(.+?)$",
        lowered,
    )
    if m:
        target = m.group(1).strip()
        # Only resolve if the target is a known folder name.
        if target in {
            "downloads", "download", "documents", "document",
            "docs", "desktop", "pictures", "photos", "music",
            "videos", "projects", "workspace", "reports",
            "backups", "backup", "home", "root",
        }:
            return ContextResolution(
                resolved=True,
                decision={
                    "level": 3,
                    "mode": "os",
                    "intent": "folder.open",
                    "operation": "folder.open",
                    "target": target,
                    "application": None,
                    "parameters": {
                        "folder": target,
                        "context_carried_from_first_clause": (
                            hint.primary_target
                        ),
                        "original_fragment": fragment,
                    },
                    "confidence": 0.92,
                    "reason": (
                        "Context-resolved: the user is in a "
                        "file manager (from the 1st clause) "
                        "and the 2nd clause names a standard "
                        "folder to open."
                    ),
                },
                description=(
                    f"Open the {target!r} folder in the "
                    f"file manager from the 1st clause."
                ),
                family="file_manager_open_folder",
            )

    # ---- show current / go home / navigate up ----
    if lowered in {
        "show the current folder", "show current folder",
        "where am i", "go home", "go to home",
        "navigate home", "navigate up", "go up",
        "show my home", "show home folder",
    }:
        return ContextResolution(
            resolved=True,
            decision={
                "level": 3,
                "mode": "os",
                "intent": "folder.open",
                "operation": "folder.open",
                "target": "home",
                "application": None,
                "parameters": {
                    "folder": "home",
                    "context_carried_from_first_clause": (
                        hint.primary_target
                    ),
                    "original_fragment": fragment,
                    "navigation": "home",
                },
                "confidence": 0.90,
                "reason": (
                    "Context-resolved: the user is in a "
                    "file manager (from the 1st clause) and "
                    "the 2nd clause is a home navigation."
                ),
            },
            description=(
                "Navigate to the home folder in the file "
                "manager from the 1st clause."
            ),
            family="file_manager_navigate_home",
        )

    return None


# =====================================================================
# BROWSER-ACTION RESOLUTION (Level 3.20)
# =====================================================================
#
# When the 1st clause opened a browser, the 2nd clause's
# browser-control verbs (bookmark, refresh, go back, etc.)
# are resolved to the closest existing browser capability.
# New capabilities (browser.bookmark, browser.refresh,
# browser.clear_history) are added to the executor as
# best-effort fallbacks.


_BROWSER_ACTION_PATTERNS = (
    # (regex on the 2nd clause, intent, description)
    (
        re.compile(
            r"^(?:please\s+)?(?:bookmark(?:\s+this)?(?:\s+page)?|"
            r"add\s+(?:this\s+)?(?:page\s+)?to\s+bookmarks|"
            r"save\s+(?:this\s+)?(?:page\s+)?to\s+bookmarks)$",
            re.IGNORECASE,
        ),
        "browser.bookmark",
        "Bookmark the current page in the browser.",
        "browser_bookmark",
    ),
    (
        re.compile(
            r"^(?:please\s+)?(?:clear\s+(?:my\s+)?(?:browsing\s+)?history|"
            r"clear\s+(?:my\s+)?cache|clear\s+cookies)$",
            re.IGNORECASE,
        ),
        "browser.clear_history",
        "Clear browsing history in the browser.",
        "browser_clear_history",
    ),
    (
        re.compile(
            r"^(?:please\s+)?(?:refresh(?:\s+the\s+page)?|"
            r"reload(?:\s+the\s+page)?)$",
            re.IGNORECASE,
        ),
        "browser.refresh",
        "Refresh the current page in the browser.",
        "browser_refresh",
    ),
    (
        re.compile(
            r"^(?:please\s+)?(?:go\s+back|navigate\s+back|"
            r"go\s+forward|navigate\s+forward)$",
            re.IGNORECASE,
        ),
        "browser.go_back",
        "Navigate back/forward in the browser.",
        "browser_navigate",
    ),
    (
        re.compile(
            r"^(?:please\s+)?(?:open\s+(?:a\s+)?new\s+tab)$",
            re.IGNORECASE,
        ),
        "browser.open_tab",
        "Open a new tab in the browser.",
        "browser_open_tab",
    ),
    (
        re.compile(
            r"^(?:please\s+)?(?:close\s+(?:the\s+)?(?:current\s+)?tab|"
            r"close\s+this\s+tab)$",
            re.IGNORECASE,
        ),
        "browser.close_tab",
        "Close the current tab in the browser.",
        "browser_close_tab",
    ),
    (
        re.compile(
            r"^(?:please\s+)?(?:reopen\s+(?:the\s+)?(?:last\s+)?tab|"
            r"undo\s+close\s+tab)$",
            re.IGNORECASE,
        ),
        "browser.switch_tab",
        "Reopen the last closed tab in the browser.",
        "browser_reopen_tab",
    ),
)


def _browser_action_resolution(
    hint: ContextHint, fragment: str,
    current_decision: Optional[Dict[str, Any]] = None,
) -> Optional[ContextResolution]:
    """Resolve a 2nd clause as a browser-control action when
    the 1st clause opened a browser."""

    if hint.category != "browser_app":
        return None

    for pattern, intent, description, family in _BROWSER_ACTION_PATTERNS:
        if pattern.match(fragment.strip()):
            return ContextResolution(
                resolved=True,
                decision={
                    "level": 3,
                    "mode": "os",
                    "intent": intent,
                    "operation": intent,
                    "target": hint.primary_application or "browser",
                    "application": hint.primary_application,
                    "parameters": {
                        "context_carried_from_first_clause": (
                            hint.primary_application
                        ),
                        "original_fragment": fragment,
                    },
                    "confidence": 0.90,
                    "reason": (
                        f"Context-resolved: the user already "
                        f"opened a browser (from the 1st clause) "
                        f"and the 2nd clause is a browser-action."
                    ),
                },
                description=description,
                family=family,
            )

    return None


# =====================================================================
def _app_create_document_resolution(
    hint: ContextHint, fragment: str,
    current_decision: Optional[Dict[str, Any]] = None,
) -> Optional[ContextResolution]:
    """Resolve a 2nd clause as a document creation action
    when the 1st clause opened an app that can create
    documents.
    """

    app_name = (hint.primary_application or hint.primary_target or "")
    if not isinstance(app_name, str):
        return None
    app_key = app_name.lower().strip()

    if app_key not in _APP_DOCUMENT_CAPABILITIES:
        return None

    app_info = _APP_DOCUMENT_CAPABILITIES[app_key]
    lowered = fragment.lower().strip()

    # The 2nd clause must contain a create-verb.
    _app_create_verbs = (
        r"start\s+a?\s*new|"
        r"create\s+a?\s*new|"
        r"make\s+a?\s*new|"
        r"write\s+(?:a\s+)?new|"
        r"open\s+a?\s*new|"
        r"begin\s+a?\s*new"
    )
    if not re.search(_app_create_verbs, lowered):
        return None

    # The 2nd clause must name a document kind this app
    # supports. We also accept a bare "blank document"
    # or "new file" as a default.
    target_kind = None
    for kind in app_info["document_kinds"]:
        if kind in lowered:
            target_kind = kind
            break

    # Accept "blank" + kind, or just "blank" as a default.
    if target_kind is None and "blank" in lowered:
        target_kind = "blank " + (
            list(app_info["document_kinds"])[0]
        )

    if target_kind is None:
        return None

    intent = app_info["intent"]
    return ContextResolution(
        resolved=True,
        decision={
            "level": 3,
            "mode": "os",
            "intent": intent,
            "operation": intent,
            "target": target_kind,
            "application": app_name,
            "parameters": {
                "document_kind": target_kind,
                "context_carried_from_first_clause": app_name,
                "original_fragment": fragment,
                "app_context": app_key,
            },
            "confidence": 0.90,
            "reason": (
                f"Context-resolved: the user opened "
                f"{app_info['app_label']} (from the 1st "
                f"clause) and the 2nd clause asks to create "
                f"a {target_kind}."
            ),
        },
        description=(
            f"Create a new {target_kind} in "
            f"{app_info['app_label']} opened by the 1st "
            f"clause."
        ),
        family="app_create_document",
    )


# =====================================================================
# PUBLIC API
# =====================================================================


# =====================================================================
# DIRECT SETTINGS SUB-PAGE RESOLUTION (Level 3.19)
# =====================================================================
#
# When the fragment itself names a settings sub-page (even
# without a prior L3 clause), the answer is unambiguous:
# open the corresponding ms-settings: URI page. This handles
# standalone phrasings such as "open accessibility" or
# "enable high contrast" that the existing decision engine
# routes to L1 because there is no installed application
# with that name.

def _direct_settings_resolution(
    fragment: str,
) -> Optional[ContextResolution]:
    """Resolve a fragment as a settings sub-page navigation
    without requiring a prior L3 context. Returns None when
    the fragment does not name a known settings sub-page.
    """

    if not fragment or not fragment.strip():
        return None

    lowered = fragment.lower().strip()
    has_settings_verb = bool(
        re.search(
            r"\b(?:open|show|go\s+to|enable|disable|"
            r"turn\s+on|turn\s+off|switch\s+on|switch\s+off|"
            r"configure|set|change|adjust|activate|deactivate|"
            r"navigate\s+to)\b",
            lowered,
        )
    )
    noun = _extract_noun_phrase(fragment)
    sub_page = _settings_sub_page_from_noun(noun)
    if not sub_page:
        sub_page = _settings_sub_page_from_noun(lowered)
    if not sub_page:
        return None

    if not (
        has_settings_verb
        or re.search(r"\b" + re.escape(sub_page) + r"\s+settings\b", lowered)
        or re.search(
            r"\b" + re.escape(SETTINGS_SUB_PAGES[sub_page]["uri_tail"]) + r"\b",
            lowered,
        )
    ):
        return None

    sub_page_info = SETTINGS_SUB_PAGES[sub_page]
    return ContextResolution(
        resolved=True,
        decision={
            "level": 3,
            "mode": "os",
            "intent": "system.open_settings",
            "operation": "system.open_settings",
            "target": sub_page,
            "application": None,
            "parameters": {
                "settings": sub_page_info["uri_tail"],
                "sub_page": sub_page,
                "context_carried_from_first_clause": None,
                "original_fragment": fragment,
            },
            "confidence": 0.90,
            "reason": (
                "Direct settings sub-page resolution: the "
                "fragment names a known Windows Settings "
                "sub-page."
            ),
        },
        description=(
            f"Open the {sub_page_info['display']} settings "
            f"page ({sub_page_info['uri_tail']}) as a direct "
            f"resolution of the fragment."
        ),
        family="direct_settings_sub_page",
    )


class ContextHintResolver:
    """Top-level resolver: takes a 1st-clause decision and a
    2nd-clause fragment and returns a structured resolution
    when one exists.

    The resolver is read-only and side-effect free.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._resolutions_attempted = 0
        self._resolutions_succeeded = 0

    def resolve(
        self,
        first_clause_decision: Dict[str, Any],
        fragment: str,
        current_decision: Optional[Dict[str, Any]] = None,
    ) -> ContextResolution:
        """Return a ContextResolution for the 2nd clause under
        the 1st-clause context, or an unresolved
        ContextResolution when no mapping applies.

        ``current_decision`` is the standalone 2nd-clause
        decision. When provided, resolvers may use it to decide
        whether the context should override the standalone
        category (e.g. a file.search in a browser context is
        correct in isolation but wrong category).
        """
        if not fragment or not fragment.strip():
            return ContextResolution(
                resolved=False,
                decision={},
                description="Empty fragment.",
                family="empty",
            )

        hint = build_context_hint(first_clause_decision)

        # Always try the standalone (no-prior-context)
        # settings sub-page resolution first: when the
        # fragment itself names a settings sub-page, the
        # answer is unambiguous regardless of prior context.
        standalone = _direct_settings_resolution(fragment)
        if standalone is not None and standalone.resolved:
            self._resolutions_attempted += 1
            self._resolutions_succeeded += 1
            return standalone

        if hint is None:
            return ContextResolution(
                resolved=False,
                decision={},
                description=(
                    "The 1st clause does not produce a known "
                    "context category (settings_app, browser_app, "
                    "file_manager) and the fragment does not "
                    "name a known settings sub-page."
                ),
                family="no_hint",
            )

        self._resolutions_attempted += 1

        for resolver in (
            _settings_resolution,
            _browser_resolution,
            _browser_action_resolution,
            _file_manager_resolution,
            _app_create_document_resolution,
        ):
            resolution = resolver(hint, fragment, current_decision)
            if resolution is not None and resolution.resolved:
                self._resolutions_succeeded += 1
                return resolution

        self._resolutions_attempted += 1

        for resolver in (
            _settings_resolution,
            _browser_resolution,
            _browser_action_resolution,
            _file_manager_resolution,
            _app_create_document_resolution,
        ):
            resolution = resolver(hint, fragment, current_decision)
            if resolution is not None and resolution.resolved:
                self._resolutions_succeeded += 1
                return resolution

        # Standalone (no-prior-context) settings sub-page
        # resolution: when the 1st clause produced no L3
        # context (e.g. the standalone fragment already
        # names a settings sub-page), try the direct
        # settings sub-page resolution.
        if hint is None or hint.category != "settings_app":
            standalone = _direct_settings_resolution(
                fragment
            )
            if standalone is not None and standalone.resolved:
                self._resolutions_succeeded += 1
                return standalone

        return ContextResolution(
            resolved=False,
            decision={},
            description=(
                f"No mapping found for fragment {fragment!r} "
                f"under context category {hint.category!r}."
            ),
            family="no_match",
        )

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "resolutions_attempted": self._resolutions_attempted,
            "resolutions_succeeded": self._resolutions_succeeded,
        }





