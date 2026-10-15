"""
Phase 3 v4 held-out corpus (dev4 / final4).

PROVENANCE — stated exactly, not approximately
----------------------------------------------
final3 is SPENT. Its per-item results were read to build the failure
taxonomy, so it can never be rescored and called blind. It remains a
valid historical record and is untouched.

v4 is built under a hard policy: NO item that appeared in scored
final3 output may be reused verbatim. Verified: the dev3 carryover
below has 0/29 phrase overlap with final3.

Composition of the 80 positives:

  * 29 dev3 CARRYOVER, read from the sealed final3 artefact rather
    than retyped (22 source="human", 7 source="assistant_draft").
    CAVEAT, stated rather than glossed: 6 of these phrases were read
    during the Step 1b routing investigation. They were never
    scored, and no fix in this phase encodes any dev3 phrase (the one
    fix that dev3 analysis suggested — inverting the looks_actionable
    cost gate — was TRIED AND REVERTED), but they are diagnosis-
    exposed rather than untouched.
  * 43 NEW hand-written positives from the project owner
    (37 source="human", 6 source="assistant_draft"), covering the
    six categories dev3 lacks: clipboard, documents, filesystem,
    spreadsheet, system, media.

  * 8 CONTEXT items and 20 NEGATIVES are agent-drafted, because they
    carry no capability answer to leak. Every context item declares
    a real `expect` so that context and negatives partition cleanly;
    final3 had one context item with expect=None, which the scorer
    miscounted inside the negative denominator (25 vs the true 23).

Enforcement lives in `phase3_v4_audit.py`, which runs the SAME
pipeline as phase3_v3_audit.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent

# =========================================================
# DEV3 CARRYOVER — never scored, read from the sealed artefact
# =========================================================

_SEALED_V3 = BACKEND / "phase3_v3_SEALED.json"
if not _SEALED_V3.exists():
    raise RuntimeError(
        f"dev3 carryover source missing: {_SEALED_V3}"
    )

_v3 = json.loads(_SEALED_V3.read_text(encoding="utf-8"))
DEV3_CARRYOVER: List[Dict[str, Any]] = list(_v3["dev3"])

_v3_final3_phrases = {
    item["phrase"] for item in _v3["final3"]
}
_reused = sorted(
    {
        item["phrase"] for item in DEV3_CARRYOVER
    } & _v3_final3_phrases
)
if _reused:
    raise RuntimeError(
        "PROVENANCE VIOLATION: dev3 carryover overlaps scored "
        f"final3 on {len(_reused)} item(s): {_reused}"
    )

# =========================================================
# NEW HAND-WRITTEN POSITIVES (43) — project owner
# =========================================================

NEW_HUMAN_POSITIVES: List[Dict[str, Any]] = [
    # -------- CLIPBOARD — 7 --------
    {
        "category": "clipboard",
        "expect": "clipboard.copy",
        "phrase": "grab that link i just highlighted",
        "source": "human",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.paste",
        "phrase": "put the text from my clipboard into this message",
        "source": "human",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.copy",
        "phrase": "copy the address of this page please",
        "source": "human",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.copy",
        "phrase": "can you copy the last paragraph i wrote?",
        "source": "human",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.copy",
        "phrase": "duplicate this entire list so i can paste it afterwards",
        "source": "human",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.copy",
        "phrase": "grab whatever i just highlighted, i may need it in a sec",
        "source": "human",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.paste",
        "phrase": "paste the content of my clipboard into this empty text field",
        "source": "human",
    },

    # -------- DOCUMENTS — 7 --------
    {
        "category": "documents",
        "expect": "file.open",
        "phrase": "open up the project proposal document from yesterday",
        "source": "human",
    },
    {
        "category": "documents",
        "expect": "document.transform",
        "phrase": "convert this text file into a clean looking pdf",
        "source": "human",
    },
    {
        "category": "documents",
        "expect": "document.edit",
        "phrase": "proofread my summary and fix any typos you find",
        "source": "human",
    },
    {
        "category": "documents",
        "expect": "document.edit",
        "phrase": "add a new bullet point at the end of the meeting notes",
        "source": "human",
    },
    {
        "category": "documents",
        "expect": "document.transform",
        "phrase": "save this draft as a markdown file on my desktop",
        "source": "human",
    },
    {
        "category": "documents",
        "expect": "document.summarize",
        "phrase": "read through this document and tell me what it's about",
        "source": "human",
    },
    {
        "category": "documents",
        "expect": "document.read",
        "phrase": "read the invoice section in this document",
        "source": "assistant_draft",
    },

    # -------- FILESYSTEM — 7 --------
    {
        "category": "filesystem",
        "expect": "folder.create",
        "phrase": "make a directory called Q4 Invoices inside my documents",
        "source": "human",
    },
    {
        "category": "filesystem",
        "expect": "file.move",
        "phrase": "move all the screenshots from my desktop to the trash",
        "source": "human",
    },
    {
        # 1c: file.search and filesystem.search are near-identical
        # twins in the registry ("Search accessible filesystem
        # locations" / "Search accessible filesystem locations for
        # matching files"). Both are correct for this request, so
        # both are accepted. This is a configuration gap, not a
        # routing defect, and it is recorded as an accept set
        # rather than "fixed" in the resolver.
        "category": "filesystem",
        "expect": "file.search",
        "accept": ["file.search", "filesystem.search"],
        "phrase": "search my whole computer for a file named tax_form_2025",
        "source": "human",
    },
    {
        "category": "filesystem",
        "expect": "file.delete",
        "phrase": "delete the old draft txt file from my downloads",
        "source": "human",
    },
    {
        "category": "filesystem",
        "expect": "folder.move",
        "phrase": "move this folder into my documents directory",
        "source": "human",
    },
    {
        "category": "filesystem",
        "expect": "file.search",
        "accept": ["file.search", "filesystem.search"],
        "phrase": "check if a file called report.txt exists in this folder",
        "source": "human",
    },
    {
        "category": "filesystem",
        "expect": "file.inspect",
        "phrase": "read the properties of this file to see when it was last modified",
        "source": "human",
    },

    # -------- SPREADSHEET — 7 --------
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.aggregate",
        "phrase": "calculate the total sum for column B in this sheet",
        "source": "human",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.sort",
        "phrase": "sort these rows alphabetically by the customer's last name",
        "source": "human",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.rank",
        "phrase": "find the row holding the biggest number in the third column",
        "source": "human",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.sort",
        "phrase": "sort this table in descending order based on the revenue column",
        "source": "human",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.filter",
        "phrase": "filter this spreadsheet to only show rows where status is active",
        "source": "human",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.calculate",
        "phrase": "calculate the average of all the numbers in this column",
        "source": "human",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.read",
        "phrase": "read the value of cell A12 for me",
        "source": "human",
    },

    # -------- SYSTEM — 7 --------
    {
        "category": "system",
        "expect": "display.brightness_set",
        "phrase": "turn down my screen brightness a little bit",
        "source": "human",
    },
    {
        "category": "system",
        "expect": "workstation.lock",
        "phrase": "lock my computer screen right now",
        "source": "human",
    },
    {
        "category": "system",
        "expect": "hardware.battery",
        "phrase": "tell me how much battery life i have left",
        "source": "human",
    },
    {
        "category": "system",
        "expect": "process.list",
        "phrase": "show me what apps are currently running in the background",
        "source": "human",
    },
    {
        "category": "system",
        "expect": "system.open_settings",
        "phrase": "open up my system settings window",
        "source": "human",
    },
    {
        "category": "system",
        "expect": "time.world_clock",
        "phrase": "what time is it in Tokyo right now?",
        "source": "assistant_draft",
    },
    {
        "category": "system",
        "expect": "network.list_wifi",
        "phrase": "which wireless networks can i join from here",
        "source": "assistant_draft",
    },

    # -------- MEDIA — 8 --------
    {
        "category": "media",
        "expect": "media.play_pause",
        "phrase": "freeze the music for a second",
        "source": "human",
    },
    {
        "category": "media",
        "expect": "screen.capture",
        "phrase": "take a quick screenshot of my entire screen",
        "source": "human",
    },
    {
        "category": "media",
        "expect": "media.next",
        "phrase": "bump to the following song in my playlist",
        "source": "human",
    },
    {
        "category": "media",
        "expect": "volume.up",
        "phrase": "turn the volume up by twenty percent",
        "source": "human",
    },
    {
        "category": "media",
        "expect": "volume.mute_toggle",
        "phrase": "unmute the audio so i can hear this clip",
        "source": "human",
    },
    {
        "category": "media",
        "expect": "media.stop",
        "phrase": "stop the audio immediately",
        "source": "assistant_draft",
    },
    {
        # "play the track after this one" / "play the track before
        # this one" are a deliberate near-minimal pair: only the
        # direction differs, so a correct router must separate
        # media.next from media.previous on direction alone.
        "category": "media",
        "expect": "media.next",
        "phrase": "play the track after this one",
        "source": "assistant_draft",
    },
    {
        "category": "media",
        "expect": "media.previous",
        "phrase": "play the track before this one",
        "source": "assistant_draft",
    },
]

HUMAN_POSITIVES: List[Dict[str, Any]] = (
    DEV3_CARRYOVER + NEW_HUMAN_POSITIVES
)

# =========================================================
# NEGATIVES — 20, agent-drafted, disjoint from v3's 23
# =========================================================

NEGATIVES: List[Dict[str, Any]] = [
    {"phrase": "what's a good way to keep notes while studying",
     "reason": "study advice", "source": "agent"},
    {"phrase": "do you know why the sky looks red at sunset",
     "reason": "science question", "source": "agent"},
    {"phrase": "say something encouraging, i had a rough day",
     "reason": "emotional support", "source": "agent"},
    {"phrase": "whats the tallest mountain in africa",
     "reason": "geography fact", "source": "agent"},
    {"phrase": "what is a hash table and how does it work",
     "reason": "concept explanation", "source": "agent"},
    {"phrase": "who wrote the book frankenstein",
     "reason": "literature fact", "source": "agent"},
    {"phrase": "i need to think this through, just talk with me",
     "reason": "no computer action", "source": "agent"},
    {"phrase": "morning all",
     "reason": "greeting", "source": "agent"},
    {"phrase": "what time should i leave to beat the traffic",
     "reason": "planning advice", "source": "agent"},
    {"phrase": "why does my program take so long to start up",
     "reason": "diagnostic question, not an OS action",
     "source": "agent"},
    {"phrase": "what are the main differences between python and ruby",
     "reason": "language comparison", "source": "agent"},
    {"phrase": "appreciate it, cheers",
     "reason": "acknowledgement", "source": "agent"},
    {"phrase": "how did the match end on saturday",
     "reason": "sports result", "source": "agent"},
    {"phrase": "recommend a podcast about ancient history",
     "reason": "recommendation", "source": "agent"},
    {"phrase": "is it going to rain tomorrow",
     "reason": "weather chat", "source": "agent"},
    {"phrase": "what does the acronym gantt mean in project management",
     "reason": "terminology question", "source": "agent"},
    {"phrase": "write a short toast for my best friends wedding",
     "reason": "creative writing", "source": "agent"},
    {"phrase": "should i take the train or drive to the airport",
     "reason": "travel advice", "source": "agent"},
    {"phrase": "baking soda versus baking powder, which one should i use",
     "reason": "cooking science", "source": "agent"},
    {"phrase": "that reminds me of something i read about black holes",
     "reason": "conversational", "source": "agent"},
]

# =========================================================
# CONTEXT — 8, agent-drafted, every one declares a real expect
# =========================================================

CONTEXT_ITEMS: List[Dict[str, Any]] = [
    {
        "category": "application",
        "expect": "application.close",
        "phrase": "close it too",
        "prior": "I have the settings window and the terminal both open.",
        "source": "agent",
    },
    {
        "category": "browser",
        "expect": "browser.extract",
        "phrase": "pull the numbers out of that",
        "prior": "The quarterly revenue table is open in the browser.",
        "source": "agent",
    },
    {
        "category": "filesystem",
        "expect": "file.copy",
        "phrase": "keep a spare on the desktop",
        "prior": "I am looking at contract_final.pdf in explorer.",
        "source": "agent",
    },
    {
        "category": "media",
        "expect": "media.next",
        "phrase": "skip this one",
        "prior": "A playlist of podcasts is currently playing.",
        "source": "agent",
    },
    {
        "category": "system",
        "expect": "display.brightness_set",
        "phrase": "make it dimmer",
        "prior": "The screen is far too bright in here.",
        "source": "agent",
    },
    {
        "category": "clipboard",
        "expect": "clipboard.paste",
        "phrase": "drop it into the message",
        "prior": "I copied the shipping address a moment ago.",
        "source": "agent",
    },
    {
        "category": "documents",
        "expect": "document.transform",
        "phrase": "make it a pdf instead",
        "prior": "The report is currently a markdown file.",
        "source": "agent",
    },
    {
        "category": "spreadsheet",
        "expect": "spreadsheet.sort",
        "phrase": "order these by name",
        "prior": "There is an unsorted list of suppliers in the sheet.",
        "source": "agent",
    },
]


# =========================================================
# HELPERS — identical semantics to phase3_v3_corpus
# =========================================================

def all_positives() -> List[Dict[str, Any]]:
    return list(HUMAN_POSITIVES) + list(CONTEXT_ITEMS)


def validate_composition() -> List[str]:
    """Enforce the composition minimums. Returns problem strings."""
    problems: List[str] = []
    positives = all_positives()
    human = [
        p for p in HUMAN_POSITIVES
        if p.get("source") == "human"
    ]

    if len(positives) < 80:
        problems.append(f"positives: {len(positives)} < 80 required")
    if len(human) < 30:
        problems.append(
            f"hand-written positives: {len(human)} < 30 required "
            f"(agent cannot author these)"
        )
    if len(NEGATIVES) < 20:
        problems.append(
            f"negatives: {len(NEGATIVES)} < 20 required"
        )
    if len(CONTEXT_ITEMS) < 8:
        problems.append(
            f"context items: {len(CONTEXT_ITEMS)} < 8 required"
        )

    required_categories = {
        "application", "gui", "browser", "filesystem", "documents",
        "spreadsheet", "system", "media", "clipboard",
    }
    present = {
        str(p.get("category", "")).lower()
        for p in positives
        if p.get("category")
    }
    missing = required_categories - present
    if missing:
        problems.append(f"categories not covered: {sorted(missing)}")

    # v4 additions: no phrase may repeat inside the corpus, and no
    # scored final3 phrase may reappear.
    seen: Dict[str, str] = {}
    for item in positives + NEGATIVES:
        phrase = item.get("phrase", "")
        if phrase in seen:
            problems.append(f"duplicate phrase: {phrase!r}")
        seen[phrase] = "v4"
    for phrase in seen:
        if phrase in _v3_final3_phrases:
            problems.append(
                f"PROVENANCE VIOLATION, scored final3 item reused: "
                f"{phrase!r}"
            )

    return problems