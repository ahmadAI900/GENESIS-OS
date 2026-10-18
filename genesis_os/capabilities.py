"""
Genesis OS — Level 3.8.6
Capability Resolution.

A capability describes something Genesis knows how to do.

Important architectural rule:

    Intent != Capability != Action

Intent:
    What the user wants.

Capability:
    What Genesis is capable of doing.

Action:
    The concrete operation performed by an executor.

Example:

    Intent:
        "Find my latest spreadsheet"

    Capability:
        filesystem.search

    Action:
        Search configured filesystem locations.

This separation prevents the workflow system from becoming
a collection of hard-coded natural-language commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, Optional


class CapabilityCategory(
    str,
    Enum,
):
    FILESYSTEM = "filesystem"
    APPLICATION = "application"
    DOCUMENT = "document"
    BROWSER = "browser"
    DATA = "data"
    COMMUNICATION = "communication"
    SYSTEM = "system"
    VISION = "vision"
    ACCESSIBILITY = "accessibility"
    GENERAL = "general"


class CapabilityAvailability(
    str,
    Enum,
):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class BlastRadius(
    str,
    Enum,
):
    """How far the damage reaches if this capability does the wrong
    thing, and — the actual question — whether it can be taken back.

    This replaces the previous model, where the confirmation decision
    was split between a boolean ``confirmed`` parameter that any caller
    (including a language model) could simply set, and a hand-maintained
    external set like ``ALWAYS_DESTRUCTIVE``. That arrangement rotted:
    the boolean was forgeable, and the external set could not see the
    arguments, so a capability could be classified one way and invoked
    against another target entirely.

    ``REVERSIBLE_LOCAL``
        The effect is confined to this machine and can be undone or
        discarded without external backup — a file that was created can
        be deleted, an edit that wrote a sibling copy leaves the
        original untouched, a window that was focused can be unfocused.
        These run with no confirmation gate at all. There is nothing to
        approve because there is nothing to lose.

    ``IRREVERSIBLE_OR_OUTWARD``
        The effect cannot be recalled from this machine alone, or it
        leaves this machine: deletion that empties the bin, anything
        sent or posted or purchased, package installation, privilege
        change, or any write outside the configured workspace. These
        require an explicit, human-issued approval token bound to the
        exact arguments of the exact call.

    Classification lives on the capability's own descriptor, next to
    ``preconditions`` / ``supported_inputs`` / ``risk_level``, so it is
    reviewed and versioned with the capability rather than in a list
    somewhere else that nothing validates.
    """

    REVERSIBLE_LOCAL = "reversible_local"
    IRREVERSIBLE_OR_OUTWARD = "irreversible_or_outward"


class Capability:
    """Legacy Level 3 capability contract.

    CapabilityDescriptor implements this marker contract so legacy
    Level 3 callers remain compatible with the richer 3.8 model.
    """

    pass


@dataclass(frozen=True)
class CapabilityRequirement:
    """
    Describes what a workflow step requires.

    This is declarative.

    It does not choose an implementation yet.
    """

    capability_id: str

    category: CapabilityCategory

    operation: str

    description: str = ""

    required_inputs: FrozenSet[str] = frozenset()

    optional_inputs: FrozenSet[str] = frozenset()

    required_permissions: FrozenSet[str] = (
        frozenset()
    )

    preferred_provider: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:

        if not self.capability_id.strip():
            raise ValueError(
                "capability_id cannot be empty."
            )

        if not self.operation.strip():
            raise ValueError(
                "operation cannot be empty."
            )


@dataclass(frozen=True)
class CapabilityDescriptor(Capability):
    """
    Canonical Genesis capability descriptor.

    This model is intentionally backward-compatible with the
    mature Level 3 execution/safety architecture.

    Level 3.8 adds richer capability metadata, but existing
    execution code must still be able to ask:

        capability.enabled

    and serialize a capability deterministically.
    """

    capability_id: str

    category: CapabilityCategory

    operation: str

    description: str

    provider: str

    version: str = "1.0"

    availability: CapabilityAvailability = (
        CapabilityAvailability.AVAILABLE
    )

    supported_inputs: FrozenSet[str] = frozenset()

    permissions: FrozenSet[str] = frozenset()

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    priority: int = 0

    # --------------------------------------------------------
    # LEGACY LEVEL 3 COMPATIBILITY
    # --------------------------------------------------------

    enabled: bool = True

    # --------------------------------------------------------
    # LEVEL 3.13: PRECONDITIONS / POSTCONDITIONS / FAILURE MODES
    # --------------------------------------------------------

    preconditions: tuple[str, ...] = ()

    postconditions: tuple[str, ...] = ()

    failure_modes: tuple[str, ...] = ()

    verification_provider: Optional[str] = None

    risk_level: str = "low"

    # --------------------------------------------------------
    # BLAST RADIUS / REVERSIBILITY
    # --------------------------------------------------------
    #
    # Defaults to IRREVERSIBLE_OR_OUTWARD on purpose. A capability that
    # nobody has consciously classified must not silently become
    # ungated: defaulting the other way would reproduce exactly the
    # failure this field exists to prevent, where a new capability is
    # added, nobody notices the question, and it ships ungated.
    # Classification is therefore an explicit act.

    blast_radius: BlastRadius = (
        BlastRadius.IRREVERSIBLE_OR_OUTWARD
    )

    # Free-text justification for the classification. Enforced non-empty
    # for IRREVERSIBLE_OR_OUTWARD and REVERSIBLE_LOCAL alike, so the
    # reviewer has to record *why* rather than just flipping a value.

    blast_radius_reason: str = ""

    multiple_providers: tuple[str, ...] = ()

    side_effects: tuple[str, ...] = ()

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    def __post_init__(self) -> None:

        if not isinstance(
            self.capability_id,
            str,
        ):
            raise TypeError(
                "capability_id must be a string."
            )

        if not self.capability_id.strip():
            raise ValueError(
                "capability_id cannot be empty."
            )

        if not isinstance(
            self.operation,
            str,
        ):
            raise TypeError(
                "operation must be a string."
            )

        if not self.operation.strip():
            raise ValueError(
                "operation cannot be empty."
            )

        if not isinstance(
            self.provider,
            str,
        ):
            raise TypeError(
                "provider must be a string."
            )

        if not 0 <= self.priority:
            raise ValueError(
                "priority cannot be negative."
            )

        if not isinstance(
            self.blast_radius,
            BlastRadius,
        ):
            raise TypeError(
                "blast_radius must be a BlastRadius."
            )

        if not self.blast_radius_reason.strip():
            raise ValueError(
                f"{self.capability_id}: blast_radius_reason is required. "
                f"Classifying blast radius without recording why is how "
                f"an unreviewed capability becomes ungated, which is the "
                f"failure this field replaces. If a capability's "
                f"reversibility genuinely cannot be established, say so "
                f"in the reason and classify it "
                f"irreversible_or_outward — do not leave it blank."
            )

    # --------------------------------------------------------
    # EFFECTIVE AVAILABILITY
    # --------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """
        Unified availability check.

        A capability is available only when it is both enabled
        and operationally available.
        """

        return (
            self.enabled
            and self.availability
            == CapabilityAvailability.AVAILABLE
        )

    @property
    def dangerous(self) -> bool:
        """
        Canonical safety classification.

        Capability resolution must never invent or override this
        value. ExecutionSafety remains authoritative.
        """

        metadata = self.metadata or {}

        return bool(
            metadata.get(
                "dangerous",
                False,
            )
        ) or self.risk_level in {"high", "critical"}

    # --------------------------------------------------------
    # REQUIREMENT MATCHING
    # --------------------------------------------------------

    def supports(
        self,
        requirement: CapabilityRequirement,
    ) -> bool:

        if not self.is_available:
            return False

        if (
            self.category
            != requirement.category
        ):
            return False

        if (
            self.operation
            != requirement.operation
        ):
            return False

        if not (
            requirement.required_inputs
            <= self.supported_inputs
        ):
            return False

        if not (
            requirement.required_permissions
            <= self.permissions
        ):
            return False

        return True

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Stable public serialization contract.

        Do not expose internal Python objects.
        """

        return {
            "capability_id": (
                self.capability_id
            ),
            "category": getattr(
                self.category,
                "value",
                str(self.category),
            ),
            "operation": self.operation,
            "description": self.description,
            "provider": self.provider,
            "version": self.version,
            "availability": getattr(
                self.availability,
                "value",
                str(self.availability),
            ),
            "enabled": self.enabled,
            "is_available": self.is_available,
            "supported_inputs": sorted(
                self.supported_inputs
            ),
            "permissions": sorted(
                self.permissions
            ),
            "metadata": dict(
                self.metadata or {}
            ),
            "priority": self.priority,
            "preconditions": list(self.preconditions),
            "postconditions": list(self.postconditions),
            "failure_modes": list(self.failure_modes),
            "verification_provider": self.verification_provider,
            "risk_level": self.risk_level,
            # Item 14E (S8). `blast_radius` and its mandatory
            # `blast_radius_reason` were the only two safety-classifying
            # fields dropped by this serializer. Every consumer that
            # received a serialized capability -- including the executor,
            # which embeds `capability.to_dict()` into plan metadata --
            # got `risk_level` and nothing telling it whether the
            # operation could be undone. Downstream, "is this
            # reversible?" simply had no answer to read.
            #
            # Serialized as the enum VALUE, matching how `category` and
            # `availability` are already handled, so no internal Python
            # object escapes (the docstring's whole contract).
            "blast_radius": getattr(
                self.blast_radius,
                "value",
                str(self.blast_radius),
            ),
            "blast_radius_reason": self.blast_radius_reason,
            "multiple_providers": list(self.multiple_providers),
            "side_effects": list(self.side_effects),
        }


@dataclass(frozen=True)
class ResolvedCapability:
    """
    Result of capability resolution.

    Contains the requirement and the concrete
    capability selected to satisfy it.
    """

    requirement: CapabilityRequirement

    capability: CapabilityDescriptor

    confidence: float

    resolution_reason: str

    alternatives_considered: tuple[
        str,
        ...
    ] = ()

    def __post_init__(self) -> None:

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )


# ============================================================
# PHASE 3 — DESCRIPTOR ENRICHMENT TABLES
# ============================================================
#
# Risk tiers ground ranking-with-risk in reversibility and blast
# radius. Preconditions name inputs that must be supplied for a
# resolution to be safe to act on. Both are applied at
# registration (CapabilityRegistry.register) so every consumer
# sees enriched descriptors. Explicit per-registration values
# always win over these defaults.

RISK_TIERS: Dict[str, str] = {
    # Irreversible destruction.
    "file.delete": "critical",
    "folder.delete": "critical",
    "cleanup.empty_recycle_bin": "critical",
    "package.uninstall": "critical",
    # Persistent state change with external or broad effects.
    "file.move": "high",
    "file.rename": "high",
    "file.copy": "high",
    "folder.move": "high",
    "folder.rename": "high",
    "folder.organize": "high",
    "document.edit": "high",
    "document.transform": "high",
    "browser.download": "medium",
    "browser.upload": "high",
    "network.connect_wifi": "high",
    "package.install": "high",
    # Persistent but scoped/ordinary changes.
    "file.create": "medium",
    "folder.create": "medium",
    "notes.create": "medium",
    "document.create_txt": "medium",
    "document.create_docx": "medium",
    "document.create_csv": "medium",
    "document.create_json": "medium",
    "document.create_markdown": "medium",
    "document.create_pdf": "medium",
    "document.create_docx_intel": "medium",
    "spreadsheet.calculate": "medium",
    "spreadsheet.filter": "medium",
    "spreadsheet.sort": "medium",
    "spreadsheet.rank": "medium",
    "spreadsheet.group_by": "medium",
    "spreadsheet.aggregate": "medium",
    "screen.capture": "medium",
    "browser.screenshot": "medium",
    "application.close": "medium",
    "clipboard.paste": "medium",
    "workstation.lock": "medium",
    "gui.click": "medium",
    "gui.double_click": "medium",
    "gui.type_text": "medium",
    "gui.paste_text": "medium",
    "gui.keyboard_action": "medium",
    "gui.hotkey": "medium",
    "gui.drag": "medium",
}

PRECONDITIONS: Dict[str, tuple] = {
    # input names that must be supplied for safe resolution.
    "file.copy": ("destination",),
    "file.move": ("destination",),
    "file.rename": ("new_name",),
    "folder.move": ("destination",),
    "folder.rename": ("new_name",),
    "document.edit": ("find_text", "replace_text"),
    "document.transform": ("output_path", "output_format"),
    "spreadsheet.filter": ("column", "condition", "value"),
    "spreadsheet.calculate": ("formula_column", "formula_template"),
    "spreadsheet.sort": ("column",),
    "spreadsheet.rank": ("rank_column",),
    "spreadsheet.group_by": ("column",),
    "browser.download": ("url", "save_path"),
    "browser.upload": ("file_path",),
    "network.connect_wifi": ("ssid",),
    "package.install": ("package",),
    "package.uninstall": ("package",),
}

RISK_PENALTIES: Dict[str, float] = {
    "low": 0.0,
    "medium": 0.02,
    "high": 0.05,
    "critical": 0.10,
}


# ---------------------------------------------------------
# PHASE 3 — SELECTION BOUNDARIES
# ---------------------------------------------------------
#
# Several capability families are near-duplicates by design
# (a base capability and an ``_intel`` / compatibility twin that
# share the same description and the same inputs). A flat
# catalog makes those pairs undecidable: no amount of model
# quality can pick between two entries whose descriptors are
# byte-identical, and the result is an arbitrary coin flip.
#
# These notes describe WHAT EACH CAPABILITY MEANS and, where a
# family is ambiguous, which member owns which semantic
# boundary. They are capability-side facts, deliberately NOT
# keyed to user phrasings: a selector that pattern-matches
# sentences has not solved semantic routing, and these notes
# must keep working for wording nobody anticipated.
#
# ``intake`` is the preferred user-facing surface for that
# semantic boundary; the base member remains the compatibility
# alias so existing callers keep resolving.

SELECTION_BOUNDARIES: Dict[str, str] = {
    # --- document reading -----------------------------------
    "document.read_intel": (
        "Owns reading a DOCUMENT file's content (Word, PDF, "
        "text). Not for web pages - use browser.extract."
    ),
    "document.read": (
        "Compatibility surface for document.read_intel. Prefer "
        "document.read_intel when choosing."
    ),
    # --- document summarising --------------------------------
    "document.summarize_intel": (
        "Owns summarising a document into a shorter brief. "
        "Prefer this over document.summarize."
    ),
    "document.summarize": (
        "Compatibility surface for document.summarize_intel."
    ),
    # --- document comparison --------------------------------
    "document.compare_intel": (
        "Owns comparing two documents. Prefer this over "
        "document.compare."
    ),
    "document.compare": (
        "Compatibility surface for document.compare_intel."
    ),
    # --- spreadsheet reading / inspection -------------------
    "spreadsheet.read_intel": (
        "Owns reading spreadsheet/workbook data as records. "
        "Prefer this over spreadsheet.read."
    ),
    "spreadsheet.read": (
        "Compatibility surface for spreadsheet.read_intel."
    ),
    "spreadsheet.inspect_intel": (
        "Owns reporting workbook STRUCTURE (sheets, columns, "
        "row counts). Prefer this over spreadsheet.inspect."
    ),
    "spreadsheet.inspect": (
        "Compatibility surface for spreadsheet.inspect_intel."
    ),
    # --- browser find ---------------------------------------
    "browser.find": (
        "Owns locating text on the current web page. Prefer "
        "this over browser.find_text."
    ),
    "browser.find_text": (
        "Compatibility surface for browser.find."
    ),
    # --- application inspection -----------------------------
    "application.inspect": (
        "Owns reporting an application's identity and runtime "
        "state. Prefer this over application."
        "inspect_window_content."
    ),
    "application.inspect_window_content": (
        "Compatibility surface for application.inspect."
    ),
    # --- the two "make a PDF" boundaries --------------------
    "document.transform": (
        "CONVERTING AN EXISTING document into another format "
        "(for example an existing Word file to PDF). Requires "
        "an input path. When the user is authoring brand new "
        "content in a target format, use document.create_* "
        "instead."
    ),
    "document.create_pdf": (
        "AUTHORING a brand-new PDF from supplied text content. "
        "Not for converting an existing file - that is "
        "document.transform."
    ),
    "document.create_txt": (
        "AUTHORING a brand-new plain text file from supplied "
        "content."
    ),
    # --- web page text vs document text ---------------------
    "browser.extract": (
        "Extracting text from a WEB PAGE currently loaded in "
        "the browser. For a document FILE use "
        "document.read_intel instead."
    ),
    # --- screen capture is the only capture surface ---------
    "screen.capture": (
        "The ONLY capability that captures the screen or takes "
        "a screenshot. There is no screen.take or screen."
        "screenshot; this is the correct id for any "
        "'screenshot' / 'capture the screen' request."
    ),
    # --- closing things -------------------------------------
    "application.close": (
        "Closing a running desktop APPLICATION. Window layout "
        "operations (minimise all, restore, show desktop) are "
        "window.* and none of them close an application."
    ),
    # --- sound vs brightness --------------------------------
    "volume.down": (
        "Reducing AUDIO output volume. Never use a display or "
        "brightness capability for a request about sound."
    ),
    "volume.up": "Increasing AUDIO output volume.",
    "volume.set": "Setting AUDIO volume to an exact percentage.",
    "volume.get": "Reading the current AUDIO volume level.",
    "volume.mute_toggle": "Muting or unmuting AUDIO output.",
    "display.brightness_get": (
        "Reading current screen BRIGHTNESS. About the screen's "
        "light level, not audio."
    ),
    "display.brightness_set": (
        "Changing screen BRIGHTNESS. About the screen's light "
        "level, never audio - audio is volume.*"
    ),
    # --- storage vs system stats ----------------------------
    "hardware.storage": (
        "Reporting DISK SPACE / storage per drive. For CPU, "
        "memory and uptime use hardware.stats."
    ),
    "hardware.stats": (
        "Reporting CPU, memory and uptime. For disk space use "
        "hardware.storage."
    ),
    # --- media transport ------------------------------------
    "media.play_pause": (
        "Toggling play/pause, or reporting what is currently "
        "playing, on the active media app. For skipping tracks "
        "use media.next / media.previous."
    ),
    "media.next": "Skipping forward to the next media track.",
    "media.previous": "Going back to the previous media track.",
    "media.stop": "Stopping media playback entirely.",
    # --- file organisation ----------------------------------
    "folder.organize": (
        "SORTING / TIDYING the contents of a folder as a whole "
        "(put these files in order). Moving one named item to "
        "another location is file.move or folder.move."
    ),
    "file.move": (
        "Moving ONE named file to another location. For "
        "tidying a whole folder use folder.organize."
    ),
    # --- web search -----------------------------------------
    "browser.search": (
        "Running a SEARCH QUERY through a search engine. For "
        "opening a known URL use browser.open_url."
    ),
    "browser.open_url": (
        "Opening a specific known address. For a query use "
        "browser.search."
    ),
    # --- sorting spreadsheets -------------------------------
    "spreadsheet.sort": (
        "SORTING spreadsheet rows by a column. For ranking rows "
        "by a computed value use spreadsheet.rank."
    ),
    "spreadsheet.rank": (
        "Adding a RANK column computed from existing values."
    ),
    # --- clipboard ------------------------------------------
    "clipboard.copy": "Putting content onto the clipboard.",
    "clipboard.paste": "Taking content off the clipboard.",
    # --- recycle bin ----------------------------------------
    "cleanup.empty_recycle_bin": (
        "ERASING the recycle bin's contents. Reporting what is "
        "in the recycle bin is cleanup.recycle_bin_query."
    ),
    "cleanup.recycle_bin_query": (
        "REPORTING the recycle bin's contents without deleting."
    ),
    # --- text file creation vs generic creation ------------
    "document.create": (
        "Generic authoring entry point. Prefer the specific "
        "document.create_<format> when the target format is "
        "known."
    ),
    "file.create": (
        "Creating an empty file on disk. To author content, "
        "prefer the matching document.create_* capability."
    ),
    # --- text input vs authoring ----------------------------
    "gui.type_text": (
        "TYPING text into whichever window currently has focus. "
        "For authoring a new document use document.create_*."
    ),
}


def enrich_descriptor(
    descriptor: CapabilityDescriptor,
) -> CapabilityDescriptor:
    """
    Apply enrichment tables to a descriptor that leaves risk or
    preconditions at their defaults. Explicit values win.
    """
    from dataclasses import replace

    updates = {}

    if (
        descriptor.risk_level == "low"
        and descriptor.capability_id in RISK_TIERS
    ):
        updates["risk_level"] = RISK_TIERS[
            descriptor.capability_id
        ]

    if (
        not descriptor.preconditions
        and descriptor.capability_id in PRECONDITIONS
    ):
        updates["preconditions"] = PRECONDITIONS[
            descriptor.capability_id
        ]

    if not updates:
        return descriptor

    return replace(descriptor, **updates)