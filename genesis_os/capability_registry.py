"""
Genesis OS — Capability Registry

Backward-compatible capability catalog shared by the
Level 3 execution/safety architecture.

Architecture:

    CapabilityRegistry
          |
          +-- legacy Level 3.6 API
          |
          +-- Level 3.8 capability descriptors
          |
          +-- safety classification
          |
          +-- deterministic discovery

IMPORTANT:

This registry is intentionally shared at class level.

Existing Genesis Level 3 components historically use:

    CapabilityRegistry.get("application.open")

and:

    CapabilityRegistry.exists("application.open")

The Level 3.8 resolver may also receive a registry instance.
Because the public registry methods are class methods, both
forms remain compatible.
"""

from __future__ import annotations

import functools
from dataclasses import replace
from threading import RLock
from typing import Any, Dict, FrozenSet, Iterable, Optional

from .capabilities import (
    BlastRadius,
    CapabilityAvailability,
    CapabilityCategory,
    Capability,
    CapabilityDescriptor,
    CapabilityRequirement,
)
from .capability_catalog import ALIASES, CAPABILITIES


# ============================================================
# REGISTRY ERRORS
# ============================================================

class CapabilityRegistryError(RuntimeError):
    """Base registry error."""


class CapabilityAlreadyRegisteredError(
    CapabilityRegistryError
):
    """Raised when a capability is already registered."""


class CapabilityNotFoundError(
    CapabilityRegistryError
):
    """Raised when a requested capability does not exist."""


# ============================================================
# REGISTRY
# ============================================================

class _HybridMethod:
    """
    Descriptor letting one method work on the class AND on an instance.

    Genesis calls this registry both ways: the canonical catalog is
    built once through the class (``CapabilityRegistry.register(...)``),
    while seeding code and tests hold an instance
    (``registry = CapabilityRegistry(); register_default_capabilities(registry)``).

    Before this descriptor every accessor was a classmethod backed by
    class-level storage, so registering through an instance mutated
    GLOBAL state. MEASURED: ``register_default_capabilities(CapabilityRegistry())``
    rewrote ``application.close``'s operation from ``application.close``
    to ``close``, which made
    ``test_level3_6_capability_registry::test_application_capabilities_are_discoverable``
    fail whenever it ran after ``test_level3_8_6_capability_resolution``.
    Those two tests assert contradictory definitions of the same ids,
    so no ordering luck can satisfy both: registration through an
    instance has to stay local to that instance.

    Bound to the class    -> ``owner`` is the class (global store).
    Bound to an instance  -> ``owner`` is that instance (overlay).
    """

    def __init__(self, func):
        self._func = func
        functools.update_wrapper(self, func)

    def __get__(self, obj, objtype=None):
        owner = objtype if obj is None else obj
        return functools.partial(self._func, owner)


# ============================================================
# CATALOG-GAP BLAST-RADIUS CLASSIFICATION
# ============================================================
#
# Capabilities registered by CapabilityRegistry._register_catalog_gap_capabilities:
# the id exists in capability_catalog.CAPABILITIES but has no hand-written
# descriptor, so the registry synthesises one. Without an entry here they
# would inherit the field default with no recorded justification.
#
# These are classified on the same standard as every other capability:
# a read-only or locally-reversible operation is reversible_local; an
# operation that mutates a workbook is held at irreversible_or_outward
# pending the spreadsheet overwrite-semantics investigation recorded as
# OPEN QUESTION 8 in the Step 2 classification report.

_CATALOG_GAP_CLASSIFICATION = {
    "application.window_list": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Reads the list of visible windows; changes no state.",
    ),
    "document.create": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Creates a new document artifact; deleting it undoes the action.",
    ),
    "document.inspect": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Inspects a document without modifying it.",
    ),
    "document.search": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Searches document contents without modifying them.",
    ),
    "gui.double_click": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Drives local UI state; reversible by navigating away. Subject to the "
        "same dynamic-signal question as browser.click (OPEN QUESTION 5).",
    ),
    "gui.drag": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Drives local UI state; reversible by navigating away. Subject to the "
        "same dynamic-signal question as browser.click (OPEN QUESTION 5).",
    ),
    "gui.hotkey": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Sends a keystroke to local UI state. Outward effects happen at a "
        "later send/submit action, which must independently default to "
        "irreversible_or_outward (fork decision 1).",
    ),
    "gui.inspect_ui_tree": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Reads the accessibility/UI tree without modifying it.",
    ),
    "gui.wait": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Waits for a UI condition; changes nothing.",
    ),
    "gui.wait_for_state": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Waits for a UI condition; changes nothing.",
    ),
    "gui.wait_for_window": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Waits for a window to appear; changes nothing.",
    ),
    "spreadsheet.add_column": (
        BlastRadius.REVERSIBLE_LOCAL,
        "VERIFIED 2026-10-07 with hash-checks: calling add_column with "
        "output == source returns success=False and the error 'Output must "
        "not overwrite the source artifact.' The guard is structural "
        "(_resolve_output compares abspath(source) to abspath(destination) "
        "and raises); the default destination is a sibling with a numeric "
        "counter on collision. Consistent with the six hand-registered "
        "spreadsheet mutators, which were verified the same way.",
    ),
    "spreadsheet.update_cell": (
        BlastRadius.REVERSIBLE_LOCAL,
        "VERIFIED 2026-10-07 with hash-checks: calling update_cell with "
        "output == source returns success=False and the error 'Output must "
        "not overwrite the source artifact.' The guard is structural "
        "(_resolve_output); prior cell contents are therefore not "
        "destroyed in place. Consistent with the six hand-registered "
        "spreadsheet mutators.",
    ),
    "spreadsheet.create_from_dicts": (
        BlastRadius.REVERSIBLE_LOCAL,
        "Creates a new workbook artifact; deleting it undoes the action.",
    ),
    "spreadsheet.update_cell": (
        BlastRadius.REVERSIBLE_LOCAL,
        "VERIFIED 2026-10-07 with hash-checks: update_cell with output == "
        "source returns success=False and the error 'Output must not "
        "overwrite the source artifact.' Structural guard via "
        "_resolve_output.",
    ),
    "spreadsheet.sort": (
        BlastRadius.REVERSIBLE_LOCAL,
        "VERIFIED 2026-10-07 with hash-checks: sort with output == source "
        "returns success=False and the error 'Output must not overwrite the "
        "source artifact.' Structural guard via _resolve_output.",
    ),
}


class CapabilityRegistry:
    """
    Genesis OS capability registry.

    The registry is shared across the Level 3 execution
    architecture.

    This preserves the established Level 3.6 API while
    supporting the richer Level 3.8 CapabilityDescriptor model.

    Storage is class-level for the canonical catalog, plus a
    per-instance overlay so registering through an instance never
    mutates global state.
    """

    def __init__(self) -> None:
        self._local_capabilities: Dict[
            str, CapabilityDescriptor
        ] = {}

    @staticmethod
    def _store_for(owner: Any) -> Dict[str, CapabilityDescriptor]:
        """Class storage when bound to the class, else the overlay."""
        local = getattr(owner, "_local_capabilities", None)
        if local is None:
            return owner._capabilities
        return local

    @staticmethod
    def _visible_to(owner: Any) -> Dict[str, CapabilityDescriptor]:
        """The instance overlay wins over class storage."""
        local = getattr(owner, "_local_capabilities", None)
        if not local:
            return owner._capabilities
        merged = dict(owner._capabilities)
        merged.update(local)
        return merged

    VERSION = "3.8.6"
        # --------------------------------------------------------
    # LEGACY CATEGORY CONSTANTS
    # --------------------------------------------------------
    #
    # Existing Level 3 code/tests use these as stable public
    # registry constants. Keep them as part of the contract.

    APPLICATION = CapabilityCategory.APPLICATION
    FILESYSTEM = CapabilityCategory.FILESYSTEM
    DOCUMENT = CapabilityCategory.DOCUMENT
    DATA = CapabilityCategory.DATA
    SYSTEM = CapabilityCategory.SYSTEM
    PROCESS = CapabilityCategory.SYSTEM
    BROWSER = CapabilityCategory.BROWSER
    NETWORK = CapabilityCategory.SYSTEM

    _lock = RLock()

    _capabilities: Dict[
        str,
        CapabilityDescriptor,
    ] = {}

    # Explicitly dangerous operations.

    _dangerous_operations = frozenset({
        "file.delete",
        "filesystem.delete",
        "file.move",
        "file.rename",
        "file.copy",
        "filesystem.move",
        "filesystem.rename",
        "system.shutdown",
        "system.restart",
    })

    # --------------------------------------------------------
    # REGISTRATION
    # --------------------------------------------------------

    @_HybridMethod
    def register(
        self,
        capability: CapabilityDescriptor,
        *,
        replace: bool = False,
    ) -> None:
        """
        Register a CapabilityDescriptor.

        Class-level storage intentionally preserves the
        historical Genesis capability catalog behavior. Registration
        through an INSTANCE is local to that instance and never
        mutates the class-level catalog (see _HybridMethod).
        """

        if not isinstance(
            capability,
            CapabilityDescriptor,
        ):
            raise TypeError(
                "CapabilityRegistry.register() expects "
                "CapabilityDescriptor."
            )

        capability_id = (
            capability.capability_id.strip()
        )

        if not capability_id:
            raise ValueError(
                "Capability ID cannot be empty."
            )

        # Phase 3 enrichment: risk tiers + preconditions from the
        # canonical tables (explicit values always win).
        from genesis_os.capabilities import enrich_descriptor
        capability = enrich_descriptor(capability)

        with CapabilityRegistry._lock:

            store = self._store_for(self)

            if (
                capability_id
                in store
                and not replace
            ):
                raise (
                    CapabilityAlreadyRegisteredError(
                        "Capability already registered: "
                        f"{capability_id}"
                    )
                )

            store[
                capability_id
            ] = capability

    # --------------------------------------------------------
    # UNREGISTER
    # --------------------------------------------------------

    @classmethod
    def unregister(
        cls,
        capability_id: str,
    ) -> None:

        capability_id = cls._normalize(
            capability_id
        )

        with cls._lock:

            if (
                capability_id
                not in cls._capabilities
            ):
                raise CapabilityNotFoundError(
                    capability_id
                )

            del cls._capabilities[
                capability_id
            ]

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------
    @_HybridMethod
    def get(
        self,
        capability_id: str,
    ) -> CapabilityDescriptor:
        """
        Return a registered capability.

        Compatible with:

            CapabilityRegistry.get("application.open")

        and:

            registry.get("application.open")
        """

        capability_id = CapabilityRegistry._normalize(
            capability_id
        )

        visible = self._visible_to(self)

        with CapabilityRegistry._lock:

            capability = visible.get(capability_id)
            if capability is None:
                alias = ALIASES.get(capability_id)
                if alias:
                    capability = visible.get(alias)

        if capability is None:
            raise CapabilityNotFoundError(
                capability_id
            )

        return capability

    # --------------------------------------------------------
    # EXISTS
    # --------------------------------------------------------

    @_HybridMethod
    def exists(
        self,
        capability_id: str,
    ) -> bool:
        """
        Return whether a capability is registered.

        Never raises for an unknown capability.
        """

        if not capability_id:
            return False

        capability_id = CapabilityRegistry._normalize(capability_id)
        visible = self._visible_to(self)
        with CapabilityRegistry._lock:
            return (
                capability_id in visible
                or ALIASES.get(capability_id, "") in visible
            )

    # --------------------------------------------------------
    # ALL
    # --------------------------------------------------------

    @_HybridMethod
    def all(
        self,
    ) -> tuple[
        CapabilityDescriptor,
        ...
    ]:

        visible = self._visible_to(self)
        with CapabilityRegistry._lock:

            return tuple(
                visible[
                    key
                ]
                for key in sorted(
                    visible
                )
            )

    # --------------------------------------------------------
    # CANDIDATES
    # --------------------------------------------------------

    @_HybridMethod
    def candidates(
        self,
        requirement: CapabilityRequirement,
    ) -> tuple[
        CapabilityDescriptor,
        ...
    ]:

        if not isinstance(
            requirement,
            CapabilityRequirement,
        ):
            raise TypeError(
                "requirement must be "
                "CapabilityRequirement."
            )

        visible = self._visible_to(self)

        with CapabilityRegistry._lock:

            matches = [
                capability
                for capability
                in visible.values()
                if capability.supports(
                    requirement
                )
            ]

        matches.sort(
            key=lambda item: (
                -item.priority,
                item.capability_id,
            )
        )

        return tuple(matches)

    # --------------------------------------------------------
    # CLASSIFY
    # --------------------------------------------------------

    @classmethod
    def classify(
        cls,
        operation: Any,
    ) -> str:
        """
        Classify an operation.

        Results:

            invalid
            supported
            unknown

        This preserves the distinction between malformed
        input and an otherwise valid but unsupported operation.
        """

        if not isinstance(
            operation,
            str,
        ):
            return "invalid"

        operation = operation.strip()

        if not operation:
            return "invalid"

        if cls.exists(operation):
            return "supported"

        return "unknown"

    # --------------------------------------------------------
    # DANGER CLASSIFICATION
    # --------------------------------------------------------

    @classmethod
    def is_dangerous(
        cls,
        operation: Any,
    ) -> bool:
        """
        Determine whether an operation requires a stronger
        safety/confirmation path.
        """

        if not isinstance(
            operation,
            str,
        ):
            return False

        operation = operation.strip()

        if not operation:
            return False

        if operation in cls._dangerous_operations:
            return True

        capability = (
            cls._capabilities.get(
                operation
            )
        )

        if capability is None:
            return False

        metadata = (
            capability.metadata
            or {}
        )

        return bool(
            metadata.get(
                "dangerous",
                False,
            )
        )

    # --------------------------------------------------------
    # OPERATIONS
    # --------------------------------------------------------

    @classmethod
    def operations(
        cls,
    ) -> tuple[str, ...]:
        """
    Return canonical capability IDs.

    The public Level 3 API historically exposed operation names,
    but workflow planning now requires stable capability IDs.

    Therefore IDs are returned exactly as registered.
        """

        with cls._lock:
            return tuple(
                sorted(
                    cls._capabilities.keys()
                )
            )

    # --------------------------------------------------------
    # CATEGORY DISCOVERY
    # --------------------------------------------------------

    @classmethod
    def by_category(
        cls,
        category: Any,
    ) -> tuple[
        CapabilityDescriptor,
    ...
    ]:
        """
    Return all capabilities belonging to a category.

    Results are deterministic and preserve the complete
    capability IDs such as:

        application.open
        application.close
        application.inspect
        application.list
        """

        if category is None:
            return ()

        category_value = getattr(
            category,
            "value",
            category,
        )

        category_value = str(
            category_value
        ).strip().lower()

        if not category_value:
            return ()

        with cls._lock:

            matches = []

            for capability in (
                cls._capabilities.values()
            ):

                descriptor_category = getattr(
                    capability.category,
                    "value",
                    str(
                        capability.category
                    ),
                )

                descriptor_category = (
                    str(
                        descriptor_category
                    )
                    .strip()
                    .lower()
                )

                if (
                    descriptor_category
                    == category_value
                ):
                    matches.append(
                        capability
                    )

        matches.sort(
            key=lambda item:
                item.capability_id
        )
        return tuple(matches)

    @classmethod
    def to_dict(
        cls,
    ) -> Dict[str, Any]:

        capabilities = [
            capability.to_dict()
            for capability in cls.all()
        ]

        return {
            "version": cls.VERSION,
            "count": len(capabilities),
            "capabilities": capabilities,
        }

    # --------------------------------------------------------
    # CLEAR
    # --------------------------------------------------------

    @classmethod
    def clear(
        cls,
    ) -> None:
        """
        Clear the registry.

        Primarily intended for isolated tests.

        Production initialization should normally use
        register(..., replace=True).
        """

        with cls._lock:
            cls._capabilities.clear()

    # --------------------------------------------------------
    # COUNT
    # --------------------------------------------------------

    @classmethod
    def count(
        cls,
    ) -> int:

        with cls._lock:
            return len(
                cls._capabilities
            )

    # --------------------------------------------------------
    # INTERNAL HELPERS
    # --------------------------------------------------------

    @staticmethod
    def _normalize(
        capability_id: str,
    ) -> str:

        if not isinstance(
            capability_id,
            str,
        ):
            raise TypeError(
                "capability_id must be a string."
            )

        capability_id = (
            capability_id.strip()
        )

        if not capability_id:
            raise ValueError(
                "capability_id cannot be empty."
            )

        return capability_id

        # --------------------------------------------------------
    # BUILT-IN CAPABILITY BOOTSTRAP
    # --------------------------------------------------------
    @classmethod
    def serialize(
        cls,
    ) -> dict[str, object]:
        """
    Serialize the complete canonical capability registry.
        """

        with cls._lock:
            capabilities = [
                capability.to_dict()
                for capability in sorted(
                    cls._capabilities.values(),
                    key=lambda item: item.capability_id,
                )
            ]

            return {
                "version": cls.VERSION,
                "count": len(capabilities),
                "capabilities": capabilities,
        }


    @classmethod
    def _register_builtin_capabilities(
        cls,
    ) -> None:
        """
        Restore the established Level 3 capability surface.

        This is intentionally part of the registry itself.

        Existing Level 3 systems import CapabilityRegistry
        directly and therefore cannot depend on a separate
        Level 3.8 bootstrap module being imported first.

        Level 3.8 extends this catalog; it does not replace it.
        """

        builtins = (

            # =================================================
            # APPLICATION INTELLIGENCE
            # =================================================

            CapabilityDescriptor(
                capability_id="application.open",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Launching an app is undone by closing it; no user data destroyed.'),
                category=CapabilityCategory.APPLICATION,
                operation="application.open",
                description="Open a resolved desktop application.",
                provider="genesis.application",
                supported_inputs=frozenset({
                "application",
                }),
                permissions=frozenset({
                "application.launch",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="application.focus",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Focus can be moved elsewhere; no persistent state changes.'),
                category=CapabilityCategory.APPLICATION,
                operation="application.focus",
                description="Bring a resolved desktop application window to the foreground.",
                provider="genesis.application",
                supported_inputs=frozenset({
                "application",
                }),
                permissions=frozenset({
                "application.control",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="application.close",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Closing loses unsaved work, which is irreversible. Kept reversible_local ONLY because the existing unsaved-changes precondition already escalates it; see OPEN QUESTION 1 in the classification report.'),
                category=CapabilityCategory.APPLICATION,
                operation="application.close",
                description="Close a running desktop application.",
                provider="genesis.application",
                supported_inputs=frozenset({
                    "application",
                }),
                permissions=frozenset({
                    "application.control",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="application.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads process/window state; changes nothing.'),
                category=CapabilityCategory.APPLICATION,
                operation="application.inspect",
                description=(
                    "Inspect a desktop application's identity "
                    "and runtime state."
                ),
                provider="genesis.application",
                supported_inputs=frozenset({
                    "application",
                }),
                permissions=frozenset({
                    "application.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="application.list",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads process/window state; changes nothing.'),
                category=CapabilityCategory.APPLICATION,
                operation="application.list",
                description=(
                    "List discoverable desktop applications."
                ),
                provider="genesis.application",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "application.read",
                }),
                priority=100,
            ),

            # =================================================
            # FILE INTELLIGENCE
            # =================================================

            CapabilityDescriptor(
                capability_id="file.read",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.read",
                description=(
                    "Read an accessible file."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.watch",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.watch",
                description=(
                    "Watch a file or folder for changes."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=50,
            ),

            CapabilityDescriptor(
                capability_id="file.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.inspect",
                description=(
                    "Inspect file identity, type and metadata."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.delete",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=('DELIBERATE, per fork decision 3: kept irreversible_or_outward despite Recycle Bin recoverability. Asking is cheap; a user who assumes the gate exists and does not check the Recycle Bin loses data irrecoverably. Preserves an already-proven approval-token mechanism.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.delete",
                description=(
                    "Delete a file after the appropriate "
                    "safety and confirmation checks."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "dangerous": True,
                    "requires_confirmation": True,
                },
                priority=100,
            ),

            # =================================================
            # PROCESS INTELLIGENCE
            # =================================================

            CapabilityDescriptor(
                capability_id="process.list",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads process state without signalling or terminating anything.'),
                category=CapabilityCategory.SYSTEM,
                operation="process.list",
                description=(
                    "List running processes."
                ),
                provider="genesis.process",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "process.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="process.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads process state without signalling or terminating anything.'),
                category=CapabilityCategory.SYSTEM,
                operation="process.inspect",
                description=(
                    "Inspect a running process."
                ),
                provider="genesis.process",
                supported_inputs=frozenset({
                    "process",
                }),
                permissions=frozenset({
                    "process.read",
                }),
                priority=100,
            ),

            # =================================================
            # EXISTING / GENERAL FILESYSTEM SURFACE
            # =================================================

            CapabilityDescriptor(
                capability_id="filesystem.search",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="filesystem.search",
                description=(
                    "Search accessible filesystem locations."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "query",
                    "location",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="filesystem.open",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="filesystem.open",
                description=(
                    "Open a resolved filesystem target."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="file.read",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.read",
                description="Read an accessible file.",
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.inspect",
                description="Inspect file metadata and identity.",
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                 permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.delete",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=('DELIBERATE, per fork decision 3: kept irreversible_or_outward despite Recycle Bin recoverability. Asking is cheap; a user who assumes the gate exists and does not check the Recycle Bin loses data irrecoverably. Preserves an already-proven approval-token mechanism.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.delete",
                description=(
                    "Delete a file through the controlled "
                    "filesystem safety path."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "dangerous": True,
                    "requires_confirmation": True,
                },
                priority=100,
            ),
            CapabilityDescriptor(
                capability_id="folder.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads directory contents or opens it in Explorer.'),
                category=CapabilityCategory.FILESYSTEM,
                 operation="folder.inspect",
                description="Inspect a folder and its metadata.",
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),
            CapabilityDescriptor(
                capability_id="folder.open",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads directory contents or opens it in Explorer.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="folder.open",
                description="Open a folder in the file explorer.",
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),
            CapabilityDescriptor(
                capability_id="folder.organize",
            blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
            blast_radius_reason=("PRODUCT CALL: Tier 1. The capability's own signature carries a dry_run parameter, which is the original authors recording their own assessment that the operation needs a dry run before committing. Its per-file destination collision semantics remain unverified. Kept conservative."),
                category=CapabilityCategory.FILESYSTEM,
                operation="folder.organize",
                description="Categorize and organize files inside a folder into standard subdirectories.",
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "confirmation_required": True,
                },
                priority=100,
            ),


            # =================================================
            # BROWSER
            # =================================================

            CapabilityDescriptor(
                capability_id="browser.search",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="search",
                description=(
                    "Search the web through a registered browser/search provider."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "query",
                }),
                permissions=frozenset({
                    "network.read",
                }),
                priority=90,
            ),

            # =================================================
            # NETWORK
            # =================================================

            CapabilityDescriptor(
                capability_id="network.list_wifi",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Lists available networks without changing connectivity.'),
                category=CapabilityCategory.SYSTEM,
                operation="list_wifi",
                description="Inspect available Wi-Fi networks.",
                provider="genesis.network",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "network.read",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="network.connect_wifi",
            blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
            blast_radius_reason=("PRODUCT CALL: Tier 1. Reconnection is not guaranteed in every network environment -- a network may be one-way, captive, or no longer in range -- so 'just reconnect' is not a reliable undo. Stranding an interactive session is an asymmetric cost, so asking first is the cheaper error."),
                category=CapabilityCategory.SYSTEM,
                operation="connect_wifi",
                description="Connect to a Wi-Fi network through the controlled network manager.",
                provider="genesis.network",
                supported_inputs=frozenset({
                    "ssid",
                    "password",
                }),
                permissions=frozenset({
                    "network.write",
                }),
                metadata={
                    "dangerous": True,
                    "requires_confirmation": True,
                },
                priority=80,
            ),

            # =================================================
            # SPREADSHEET
            # =================================================

            CapabilityDescriptor(
                capability_id="spreadsheet.sort",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 with hash-checks: calling every spreadsheet mutator with output == source returns success=False and the error 'Output must not overwrite the source artifact.' The guard is structural (_resolve_output compares abspath(source) to abspath(destination) and raises), and the default destination is a sibling '<stem>_<op><ext>' with a numeric counter on collision. Verified individually for add_column, update_cell, sort, filter_rows, calculate, rank, group_by and aggregate -- the group is uniform here, each routed through the same _resolve_output helper."),
                category=CapabilityCategory.DATA,
                operation="sort",
                description="Sort structured spreadsheet data through the controlled data surface.",
                provider="genesis.spreadsheet",
                supported_inputs=frozenset({
                    "source",
                    "column",
                }),
                permissions=frozenset({
                    "data.read",
                    "data.write",
                }),
                priority=80,
            ),

            # =================================================
            # DOCUMENT
            # =================================================

            CapabilityDescriptor(
                capability_id="document.create_docx",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="create_docx",
                description="Create a DOCX document through the controlled document surface.",
                provider="genesis.document",
                supported_inputs=frozenset({
                    "path",
                    "content",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "dangerous": True,
                    "requires_confirmation": True,
                },
                priority=80,
            ),

            CapabilityDescriptor(
                capability_id="document.read",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.read",
                description=(
                    "Read a supported document."
                ),
                provider="genesis.document",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            # =================================================
            # DATA
            # =================================================

            CapabilityDescriptor(
                capability_id="data.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Inspects data without modifying it.'),
                category=CapabilityCategory.DATA,
                operation="data.inspect",
                description=(
                    "Inspect structured data."
                ),
                provider="genesis.data",
                supported_inputs=frozenset({
                    "source",
                }),
                permissions=frozenset({
                    "data.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="data.transform",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 by inspection of os_manager.data_transform: it raises 'Data output must not overwrite the source artifact.' when destination.resolve() == source.resolve(), and defaults to a sibling '<stem>_<operation><suffix>'. This replaces the earlier classification, which had been assigned by ANALOGY with document.transform rather than verified."),
                category=CapabilityCategory.DATA,
                operation="data.transform",
                description=(
                    "Transform structured data."
                ),
                provider="genesis.data",
                supported_inputs=frozenset({
                    "source",
                    "operation",
                }),
                permissions=frozenset({
                    "data.read",
                    "data.write",
                }),
                priority=100,
            ),

            # =================================================
            # FILE EXECUTION SURFACE
            #
            # Completes the established ActionExecutor surface
            # so that natural-language file requests (for
            # example "find my IELTS essay") are recognized by
            # the execution-safety policy instead of being
            # rejected as unknown capabilities.
            #
            # Risk classification follows the Level 3 safety
            # architecture:
            #
            #     read-only  -> allowed
            #     create/copy -> allowed (mutation, verified)
            #     move/rename -> confirmation-gated
            #     delete     -> dangerous + confirmation-gated
            # =================================================

            CapabilityDescriptor(
                capability_id="file.search",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.search",
                description=(
                    "Search accessible filesystem locations "
                    "for matching files."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "query",
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.hash",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.hash",
                description=(
                    "Compute a cryptographic hash of a file."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.open",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads file state, contents, hashes or search results.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.open",
                description=(
                    "Open a resolved file with its default "
                    "registered application."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.create",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new file; deleting it undoes the action.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.create",
                description=(
                    "Create a new file through the controlled "
                    "filesystem safety path."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.copy",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Copy leaves the source intact; deleting the copy undoes the action.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="file.copy",
                description=(
                    "Copy a file through the controlled "
                    "filesystem safety path."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                    "destination",
                }),
                permissions=frozenset({
                    "filesystem.read",
                    "filesystem.write",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.move",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('A move to a free destination is undone by moving back. Escalates to irreversible_or_outward when the destination already exists, because overwriting destroys the previous contents irrecoverably (see overwrite_destination_escalation).'),
                # # blast-radius: dynamic evaluator registered in genesis_os.blast_radius
                category=CapabilityCategory.FILESYSTEM,
                operation="file.move",
                description=(
                    "Move a file after explicit user "
                    "confirmation."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                    "destination",
                }),
                permissions=frozenset({
                    "filesystem.read",
                    "filesystem.write",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="file.rename",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('A move to a free destination is undone by moving back. Escalates to irreversible_or_outward when the destination already exists, because overwriting destroys the previous contents irrecoverably (see overwrite_destination_escalation).'),
                # # blast-radius: dynamic evaluator registered in genesis_os.blast_radius
                category=CapabilityCategory.FILESYSTEM,
                operation="file.rename",
                description=(
                    "Rename a file after explicit user "
                    "confirmation."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                    "new_name",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=100,
            ),

            # =================================================
            # FOLDER EXECUTION SURFACE
            # =================================================

            CapabilityDescriptor(
                capability_id="folder.create",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a directory; removing it undoes the action.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="folder.create",
                description=(
                    "Create a new folder through the controlled "
                    "filesystem safety path."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="folder.rename",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Same as file.move: reversible to a free destination, escalates when the destination exists and would be overwritten.'),
                # # blast-radius: dynamic evaluator registered in genesis_os.blast_radius
                category=CapabilityCategory.FILESYSTEM,
                operation="folder.rename",
                description=(
                    "Rename a folder after explicit user "
                    "confirmation."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                    "new_name",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="folder.move",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Same as file.move: reversible to a free destination, escalates when the destination exists and would be overwritten.'),
                # # blast-radius: dynamic evaluator registered in genesis_os.blast_radius
                category=CapabilityCategory.FILESYSTEM,
                operation="folder.move",
                description=(
                    "Move a folder after explicit user "
                    "confirmation."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                    "destination",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="folder.delete",
            blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
            blast_radius_reason=("VERIFIED 2026-10-07: folder_manager.delete calls Path.rmdir() directly. There is NO Recycle Bin path, unlike file.delete's _delete_to_recycle_bin. So this is genuinely irreversible on its own evidence, not by analogy with file.delete. It also refuses a non-empty folder without an explicit recursive policy. Tier 1 on verified grounds, stronger than file.delete's deliberate argument."),
                category=CapabilityCategory.FILESYSTEM,
                operation="folder.delete",
                description=(
                    "Delete an empty folder after explicit "
                    "user confirmation."
                ),
                provider="genesis.filesystem",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "dangerous": True,
                    "requires_confirmation": True,
                },
                priority=100,
            ),

            # =================================================
            # BROWSER / SYSTEM EXECUTION SURFACE
            # =================================================

            CapabilityDescriptor(
                capability_id="browser.open_url",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="open_url",
                description=(
                    "Open a URL in the default browser."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "url",
                }),
                permissions=frozenset({
                    "network.read",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="system.status",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads system status.'),
                category=CapabilityCategory.SYSTEM,
                operation="status",
                description=(
                    "Report Genesis OS system intelligence status."
                ),
                provider="genesis.system",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "system.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="system.shutdown",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=(
                    "Machine shutdown - no recovery path within Genesis's "
                    "control. Registered UNAVAILABLE because neither "
                    "OSManager nor ActionExecutor implements it: the "
                    "operation previously existed only as a name in "
                    "_dangerous_operations, leaving it invisible to the "
                    "blast-radius model entirely. Classifying it here means "
                    "a future implementation cannot make it ungated by "
                    "accident."
                ),
                availability=CapabilityAvailability.UNAVAILABLE,
                category=CapabilityCategory.SYSTEM,
                operation="system.shutdown",
                description="Shut the machine down.",
                provider="genesis.system",
                supported_inputs=frozenset(),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="system.restart",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=(
                    "Machine restart - no recovery path within Genesis's "
                    "control. Registered UNAVAILABLE because neither "
                    "OSManager nor ActionExecutor implements it: the "
                    "operation previously existed only as a name in "
                    "_dangerous_operations, leaving it invisible to the "
                    "blast-radius model entirely. Classifying it here means "
                    "a future implementation cannot make it ungated by "
                    "accident."
                ),
                availability=CapabilityAvailability.UNAVAILABLE,
                category=CapabilityCategory.SYSTEM,
                operation="system.restart",
                description="Restart the machine.",
                provider="genesis.system",
                supported_inputs=frozenset(),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="system.open_settings",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Opens the system settings app; reversible by closing it.'),
                category=CapabilityCategory.SYSTEM,
                operation="open_settings",
                description=(
                    "Open a supported Windows settings page."
                ),
                provider="genesis.system",
                supported_inputs=frozenset({
                    "target",
                }),
                permissions=frozenset({
                    "system.read",
                }),
                priority=100,
            ),

            # =================================================
            # MEDIA / AUDIO CONTROL (Level 3.10)
            # =================================================

            CapabilityDescriptor(
                capability_id="media.play_pause",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Local media transport control; reversible by issuing another transport command.'),
                category=CapabilityCategory.GENERAL,
                operation="play_pause",
                description=(
                    "Toggle play/pause on the active media "
                    "application through virtual media keys."
                ),
                provider="genesis.media",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "media.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="media.next",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Local media transport control; reversible by issuing another transport command.'),
                category=CapabilityCategory.GENERAL,
                operation="next",
                description="Skip to the next media track.",
                provider="genesis.media",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "media.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="media.previous",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Local media transport control; reversible by issuing another transport command.'),
                category=CapabilityCategory.GENERAL,
                operation="previous",
                description="Go to the previous media track.",
                provider="genesis.media",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "media.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="media.stop",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Local media transport control; reversible by issuing another transport command.'),
                category=CapabilityCategory.GENERAL,
                operation="stop",
                description="Stop media playback.",
                provider="genesis.media",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "media.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="volume.up",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Changing volume is undone by setting it back.'),
                category=CapabilityCategory.SYSTEM,
                operation="up",
                description="Nudge system volume up.",
                provider="genesis.audio",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "audio.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="volume.down",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Changing volume is undone by setting it back.'),
                category=CapabilityCategory.SYSTEM,
                operation="down",
                description="Nudge system volume down.",
                provider="genesis.audio",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "audio.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="volume.mute_toggle",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Changing volume is undone by setting it back.'),
                category=CapabilityCategory.SYSTEM,
                operation="mute_toggle",
                description=(
                    "Mute, unmute, or toggle system mute."
                ),
                provider="genesis.audio",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "audio.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="volume.set",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Changing volume is undone by setting it back.'),
                category=CapabilityCategory.SYSTEM,
                operation="set",
                description=(
                    "Set master volume to an exact percentage "
                    "through the Windows Core Audio API."
                ),
                provider="genesis.audio",
                supported_inputs=frozenset({
                    "percent",
                }),
                permissions=frozenset({
                    "audio.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="volume.get",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads the current volume.'),
                category=CapabilityCategory.SYSTEM,
                operation="get",
                description=(
                    "Read the current system volume level."
                ),
                provider="genesis.audio",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "audio.read",
                }),
                priority=90,
            ),

            # =================================================
            # DISPLAY (Level 3.10)
            # =================================================

            CapabilityDescriptor(
                capability_id="display.brightness_set",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Changing brightness is undone by setting it back.'),
                category=CapabilityCategory.SYSTEM,
                operation="brightness_set",
                description=(
                    "Set screen brightness to a percentage or "
                    "step it up/down."
                ),
                provider="genesis.display",
                supported_inputs=frozenset({
                    "percent",
                }),
                permissions=frozenset({
                    "display.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="display.brightness_get",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads the current brightness.'),
                category=CapabilityCategory.SYSTEM,
                operation="brightness_get",
                description="Read current screen brightness.",
                provider="genesis.display",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "display.read",
                }),
                priority=90,
            ),

            # =================================================
            # HARDWARE INTELLIGENCE (Level 3.10, read-only)
            # =================================================

            CapabilityDescriptor(
                capability_id="hardware.battery",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads hardware state.'),
                category=CapabilityCategory.SYSTEM,
                operation="battery",
                description=(
                    "Report battery level and charging state."
                ),
                provider="genesis.hardware",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "hardware.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="hardware.stats",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads hardware state.'),
                category=CapabilityCategory.SYSTEM,
                operation="stats",
                description=(
                    "Report CPU, memory, and uptime snapshot."
                ),
                provider="genesis.hardware",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "hardware.read",
                }),
                priority=100,
            ),

            # =================================================
            # CLIPBOARD / CAPTURE (Level 3.10)
            # =================================================

            CapabilityDescriptor(
                capability_id="clipboard.copy",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Writes to the clipboard; the previous clipboard is restorable.'),
                category=CapabilityCategory.GENERAL,
                operation="copy",
                description=(
                    "Copy text to the system clipboard with "
                    "readback verification."
                ),
                provider="genesis.clipboard",
                supported_inputs=frozenset({
                    "text",
                }),
                permissions=frozenset({
                    "clipboard.write",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="clipboard.paste",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads the clipboard into local UI state; the source clipboard is untouched.'),
                category=CapabilityCategory.GENERAL,
                operation="paste",
                description="Read the current clipboard text.",
                provider="genesis.clipboard",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "clipboard.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="screen.capture",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('PRODUCT CALL: Tier 2 for blast radius. Capture is entirely local and writes a deletable image file; nothing is transmitted. NOTE: blast radius measures reversibility, NOT confidentiality -- a screen capture is sensitive content even though deleting it undoes the action. See the named privacy-sensitivity gap recorded for browser.download and screen.capture.'),
                category=CapabilityCategory.GENERAL,
                operation="capture",
                description=(
                    "Capture the screen to an image file with "
                    "decode verification."
                ),
                provider="genesis.capture",
                supported_inputs=frozenset({
                    "path",
                }),
                permissions=frozenset({
                    "screen.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="web.research",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Fetches and returns data; nothing local is modified.'),
                category=CapabilityCategory.BROWSER,
                operation="research",
                description=(
                    "Search the live internet and return "
                    "structured results."
                ),
                provider="genesis.web",
                supported_inputs=frozenset({
                    "query",
                }),
                permissions=frozenset({
                    "network.read",
                }),
                priority=90,
            ),

            # =================================================
            # WINDOW MANAGEMENT (Level 3.12)
            # =================================================

            CapabilityDescriptor(
                capability_id="window.minimize_all",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Window and desktop layout changes are undone by restoring the window.'),
                category=CapabilityCategory.SYSTEM,
                operation="minimize_all",
                description="Minimize every open window.",
                provider="genesis.windows",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "desktop.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="window.restore",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Window and desktop layout changes are undone by restoring the window.'),
                category=CapabilityCategory.SYSTEM,
                operation="restore",
                description=(
                    "Restore previously minimized windows."
                ),
                provider="genesis.windows",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "desktop.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="window.show_desktop",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Window and desktop layout changes are undone by restoring the window.'),
                category=CapabilityCategory.SYSTEM,
                operation="show_desktop",
                description="Toggle desktop visibility.",
                provider="genesis.windows",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "desktop.control",
                }),
                priority=90,
            ),

            # =================================================
            # DAILY INTELLIGENCE (Level 3.12)
            # =================================================

            CapabilityDescriptor(
                capability_id="web.weather",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Fetches and returns data; nothing local is modified.'),
                category=CapabilityCategory.BROWSER,
                operation="weather",
                description=(
                    "Current weather for a city from the live "
                    "public weather service."
                ),
                provider="genesis.daily",
                supported_inputs=frozenset({
                    "city",
                }),
                permissions=frozenset({
                    "network.read",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="time.world_clock",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads the current time.'),
                category=CapabilityCategory.GENERAL,
                operation="world_clock",
                description="Current time in a city worldwide.",
                provider="genesis.daily",
                supported_inputs=frozenset({
                    "city",
                }),
                permissions=frozenset(),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="math.evaluate",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07: daily_intelligence parses with ast.parse(mode='eval') and evaluates against an allow-list of node types. Escape attempts were rejected: __import__('os').system(...), open(...).read(), (1).__class__.__mro__, ().__class__.__bases__[0].__subclasses__(), list comprehensions, calls, subscripting, and assignment all refused with 'Only plain arithmetic expressions are allow-listed'. It is not eval() and there is no filesystem or code-execution reach. Tier 2 confirmed on evidence."),
                category=CapabilityCategory.DATA,
                operation="evaluate",
                description=(
                    "Evaluate a pure arithmetic expression "
                    "safely."
                ),
                provider="genesis.daily",
                supported_inputs=frozenset({
                    "expression",
                }),
                permissions=frozenset(),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="hardware.storage",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads hardware state.'),
                category=CapabilityCategory.SYSTEM,
                operation="storage",
                description="Report disk space per drive.",
                provider="genesis.daily",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "hardware.read",
                }),
                priority=100,
            ),

            # =================================================
            # NOTES (Level 3.12)
            # =================================================

            CapabilityDescriptor(
                capability_id="notes.create",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new note; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="create",
                description=(
                    "Save a personal note under the user's "
                    "Documents folder with readback proof."
                ),
                provider="genesis.notes",
                supported_inputs=frozenset({
                    "text",
                }),
                permissions=frozenset({
                    "filesystem.write",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="notes.list",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Lists notes without modifying them.'),
                category=CapabilityCategory.DOCUMENT,
                operation="list",
                description="List saved notes, newest first.",
                provider="genesis.notes",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            # =================================================
            # PACKAGE MANAGEMENT (Level 3.12) — GATED
            # =================================================

            CapabilityDescriptor(
                capability_id="package.search",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Queries available packages without installing anything.'),
                category=CapabilityCategory.APPLICATION,
                operation="search",
                description=(
                    "Search the Windows Package Manager "
                    "repository. Read-only."
                ),
                provider="genesis.packages",
                supported_inputs=frozenset({
                    "query",
                }),
                permissions=frozenset({
                    "network.read",
                }),
                priority=80,
            ),

            CapabilityDescriptor(
                capability_id="package.install",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=('Installs software system-wide. Not trivially reversible: uninstall does not restore prior versions, configuration, or removed shared libraries.'),
                category=CapabilityCategory.APPLICATION,
                operation="install",
                description=(
                    "Install an application through winget "
                    "after explicit user confirmation."
                ),
                provider="genesis.packages",
                supported_inputs=frozenset({
                    "package",
                }),
                permissions=frozenset({
                    "system.install",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=70,
            ),

            CapabilityDescriptor(
                capability_id="package.uninstall",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=('Removes software system-wide. Other software may depend on it; the dependency graph is not restored by reinstalling.'),
                category=CapabilityCategory.APPLICATION,
                operation="uninstall",
                description=(
                    "Uninstall an application through winget "
                    "after explicit user confirmation."
                ),
                provider="genesis.packages",
                supported_inputs=frozenset({
                    "package",
                }),
                permissions=frozenset({
                    "system.uninstall",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=70,
            ),

            # =================================================
            # CLEANUP (Level 3.12) — GATED
            # =================================================

            CapabilityDescriptor(
                capability_id="cleanup.recycle_bin_query",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Queries Recycle Bin contents without modifying them.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="recycle_bin_query",
                description=(
                    "Report Recycle Bin item count and size. "
                    "Read-only."
                ),
                provider="genesis.cleanup",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "filesystem.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="cleanup.empty_recycle_bin",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=('Permanently destroys everything in the Recycle Bin. Irreversible.'),
                category=CapabilityCategory.FILESYSTEM,
                operation="empty_recycle_bin",
                description=(
                    "Permanently empty the Recycle Bin after "
                    "explicit user confirmation."
                ),
                provider="genesis.cleanup",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "filesystem.write",
                }),
                metadata={
                    "dangerous": True,
                    "requires_confirmation": True,
                },
                priority=60,
            ),

            # =================================================
            # WORKSTATION SECURITY (Level 3.10)
            #
            # Locking is reversible (user unlocks with their own
            # credentials), but it interrupts the session, so it
            # is confirmation-gated.
            # =================================================

            CapabilityDescriptor(
                capability_id="workstation.lock",
            blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
            blast_radius_reason=("PRODUCT CALL: Tier 1. Genesis cannot reverse a lock it does not hold the password for. There is no programmatic undo available to this system, so the operation is irreversible from Genesis's side even though a human could unlock it."),
                category=CapabilityCategory.SYSTEM,
                operation="lock",
                description=(
                    "Lock the workstation through the official "
                    "Windows API after user confirmation."
                ),
                provider="genesis.workstation",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "session.control",
                }),
                metadata={
                    "requires_confirmation": True,
                },
                priority=80,
            ),

            # =================================================
            # ADVANCED BROWSER INTELLIGENCE (Level 3.13)
            # =================================================

            CapabilityDescriptor(
                capability_id="browser.click",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=("Clicking local page content is reversible by navigating away. Escalates to irreversible_or_outward when the target's accessible text carries a high-risk signal or exposes none at all (see browser.click evaluator)."),
                # # blast-radius: dynamic evaluator registered in genesis_os.blast_radius
                category=CapabilityCategory.BROWSER,
                operation="click",
                description=(
                    "Click an element on the current page by CSS selector."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "selector",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.type",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="type",
                description=(
                    "Type text into an element on the current page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "selector",
                    "text",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.scroll",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="scroll",
                description=(
                    "Scroll the current page up or down."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "direction",
                    "amount",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.find",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="find",
                description=(
                    "Find text on the current page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "text",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.extract",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="extract",
                description=(
                    "Extract text from the current page or a specific element."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "selector",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.get_title",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="get_title",
                description=(
                    "Get the title of the current page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.get_url",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="get_url",
                description=(
                    "Get the URL of the current page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.switch_tab",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="switch_tab",
                description=(
                    "Switch to a different tab by index."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "index",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.open_tab",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="open_tab",
                description=(
                    "Open a new browser tab."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "url",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.close_tab",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="close_tab",
                description=(
                    "Close a browser tab by index or the current tab."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "index",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.get_tabs",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="get_tabs",
                description=(
                    "List all open browser tabs."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.wait",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="wait",
                description=(
                    "Wait for an element to appear on the page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "selector",
                    "timeout",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.screenshot",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="screenshot",
                description=(
                    "Take a screenshot of the current page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "path",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.get_page_state",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="get_page_state",
                description=(
                    "Capture full browser page state including title, URL, "
                    "element counts, text preview, and DOM snapshot."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.verify",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="verify",
                description=(
                    "Verify the current page state matches expected URL or title."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "expected_url",
                    "expected_title_contains",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.capabilities",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="capabilities",
                description=(
                    "Report which browser capabilities are available with the current provider."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset(),
                permissions=frozenset({
                    "browser.read",
                }),
                priority=100,
            ),

            CapabilityDescriptor(
                capability_id="browser.select",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Browser inspection and navigation; recoverable by navigating away.'),
                category=CapabilityCategory.BROWSER,
                operation="select",
                description=(
                    "Select an option from a dropdown/select element by value, label, or index."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "selector",
                    "value",
                    "label",
                    "index",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.download",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('PRODUCT CALL: Tier 2 for blast radius. Downloading is INBOUND -- it creates a local file and transmits nothing -- so deleting the file reverses it. NOTE: blast radius measures reversibility, NOT confidentiality; see the named privacy-sensitivity gap recorded for browser.download and screen.capture.'),
                category=CapabilityCategory.BROWSER,
                operation="download",
                description=(
                    "Download a file from a URL to a local path."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "url",
                    "save_path",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                    "filesystem.write",
                }),
                priority=90,
            ),

            CapabilityDescriptor(
                capability_id="browser.upload",
                blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                blast_radius_reason=('Transmits local files to a remote endpoint. Outward-facing and not recallable.'),
                category=CapabilityCategory.BROWSER,
                operation="upload",
                description=(
                    "Upload a local file to a file input element on the page."
                ),
                provider="genesis.browser",
                supported_inputs=frozenset({
                    "selector",
                    "file_path",
                    "session_id",
                }),
                permissions=frozenset({
                    "browser.control",
                    "filesystem.read",
                }),
                priority=90,
            ),

            # ============================================================
            # LEVEL 3.14+ — GUI INTERACTION CAPABILITIES
            # ============================================================

            CapabilityDescriptor(
                capability_id="gui.focus_window",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or inspects UI state without modifying it.'),
                category=CapabilityCategory.APPLICATION,
                operation="focus_window",
                description="Focus a window by title pattern match.",
                provider="genesis.gui",
                supported_inputs=frozenset({"target"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.inspect_window",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or inspects UI state without modifying it.'),
                category=CapabilityCategory.APPLICATION,
                operation="inspect_window",
                description="Inspect window state and controls.",
                provider="genesis.gui",
                supported_inputs=frozenset({"target"}),
                permissions=frozenset({"gui.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.click",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
                category=CapabilityCategory.APPLICATION,
                operation="gui.click",
                description="Click at screen coordinates.",
                provider="genesis.gui",
                supported_inputs=frozenset({"x", "y"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.type_text",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('FORK DECISION 1: typing into local UI state is itself reversible. Outward effects occur at a subsequent send/submit action, which must independently default to irreversible_or_outward.'),
                category=CapabilityCategory.APPLICATION,
                operation="gui.type_text",
                description="Type text into focused element.",
                provider="genesis.gui",
                supported_inputs=frozenset({"text"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.paste_text",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('FORK DECISION 1: typing into local UI state is itself reversible. Outward effects occur at a subsequent send/submit action, which must independently default to irreversible_or_outward.'),
                category=CapabilityCategory.APPLICATION,
                operation="gui.paste_text",
                description="Paste text from clipboard into focused element.",
                provider="genesis.gui",
                supported_inputs=frozenset({"text"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.read_visible_text",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or inspects UI state without modifying it.'),
                category=CapabilityCategory.APPLICATION,
                operation="gui.read_visible_text",
                description="Read visible text from the screen.",
                provider="genesis.gui",
                supported_inputs=frozenset(),
                permissions=frozenset({"gui.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.select",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or inspects UI state without modifying it.'),
                category=CapabilityCategory.APPLICATION,
                operation="gui.select",
                description="Select text in focused element.",
                provider="genesis.gui",
                supported_inputs=frozenset({"start", "end"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.scroll",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or inspects UI state without modifying it.'),
                category=CapabilityCategory.APPLICATION,
                operation="gui.scroll",
                description="Scroll in focused window.",
                provider="genesis.gui",
                supported_inputs=frozenset({"direction"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="gui.keyboard_action",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
                category=CapabilityCategory.APPLICATION,
                operation="gui.keyboard_action",
                description="Send a keyboard action (key press).",
                provider="genesis.gui",
                supported_inputs=frozenset({"key"}),
                permissions=frozenset({"gui.write"}),
                priority=90,
            ),

            # ============================================================
            # LEVEL 3.14+ — DOCUMENT INTELLIGENCE CAPABILITIES
            # ============================================================

            CapabilityDescriptor(
                capability_id="document.inspect_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.inspect",
                description="Inspect document metadata (format, pages, word count, author).",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"document.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.read_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.read",
                description="Read and extract text content from a document.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"document.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.search_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.search",
                description="Search within document content.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "query"}),
                permissions=frozenset({"document.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.create_txt",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.create_txt",
                description="Create a plain text document.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "content"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.create_docx_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.create_docx",
                description="Create a Word document with title and sections.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "title"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.create_csv",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.create_csv",
                description="Create a CSV spreadsheet.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "headers"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.create_json",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.create_json",
                description="Create a JSON document.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "data"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.create_markdown",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.create_markdown",
                description="Create a Markdown document.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "content"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.create_pdf",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Creates a new document; deleting it undoes the action.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.create_pdf",
                description="Create a PDF document with title and body text (requires reportlab).",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "title", "content"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.compare_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.compare",
                description="Compare two documents for differences.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path1", "path2"}),
                permissions=frozenset({"document.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                # Alias: the executor dispatches the
                # operation name "document.compare" directly
                # to OSManager.doc_compare. Safety must allow
                # it under that exact name. Without this alias
                # the capability registry only knows
                # "document.compare_intel" and the safety
                # layer denies the operation as "unknown".
                capability_id="document.compare",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.compare",
                description="Compare two documents for differences.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path1", "path2"}),
                permissions=frozenset({"document.read"}),
                priority=85,
            ),
            CapabilityDescriptor(
                capability_id="document.summarize_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.summarize",
                description="Extractive summary of a document.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"document.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                # Alias: see note on document.compare above.
                capability_id="document.summarize",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.summarize",
                description="Extractive summary of a document.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"document.read"}),
                priority=85,
            ),
            CapabilityDescriptor(
                capability_id="document.edit",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('VERIFIED 2026-10-07: writes a sibling <stem>_edited file and never overwrites the source. Original content confirmed byte-identical by hash after a real edit.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.edit",
                description="Edit a document by finding and replacing text.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "find_text", "replace_text"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.transform",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=("VERIFIED 2026-10-07: refuses output_path == input_path with 'Output must not overwrite the source artifact.' Content confirmed byte-identical by hash across txt/md/json/csv. Guard is structural (abspath equality), not incidental."),
                category=CapabilityCategory.DOCUMENT,
                operation="document.transform",
                description="Transform a document from one format to another.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "output_path", "output_format"}),
                permissions=frozenset({"document.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="document.verify",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Comparison and inspection are read-only.'),
                category=CapabilityCategory.DOCUMENT,
                operation="document.verify",
                description="Verify a document exists, is readable, and matches expected state.",
                provider="genesis.doc_intel",
                supported_inputs=frozenset({"path", "expected_content", "expected_format"}),
                permissions=frozenset({"document.read"}),
                priority=90,
            ),

            # ============================================================
            # LEVEL 3.14+ — SPREADSHEET INTELLIGENCE CAPABILITIES
            # ============================================================

            CapabilityDescriptor(
                capability_id="spreadsheet.inspect_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or compares spreadsheet data without modifying it.'),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.inspect",
                description="Inspect workbook structure (sheets, columns, row counts).",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                # Alias: see note on document.compare above.
                capability_id="spreadsheet.inspect",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or compares spreadsheet data without modifying it.'),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.inspect",
                description="Inspect workbook structure (sheets, columns, row counts).",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=85,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.read_intel",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or compares spreadsheet data without modifying it.'),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.read",
                description="Read spreadsheet data as structured records.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                # Alias: see note on document.compare above.
                capability_id="spreadsheet.read",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or compares spreadsheet data without modifying it.'),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.read",
                description="Read spreadsheet data as structured records.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=85,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.filter",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 with hash-checks: calling every spreadsheet mutator with output == source returns success=False and the error 'Output must not overwrite the source artifact.' The guard is structural (_resolve_output compares abspath(source) to abspath(destination) and raises), and the default destination is a sibling '<stem>_<op><ext>' with a numeric counter on collision. Verified individually for add_column, update_cell, sort, filter_rows, calculate, rank, group_by and aggregate -- the group is uniform here, each routed through the same _resolve_output helper."),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.filter",
                description="Filter spreadsheet rows by condition.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path", "sheet_name", "column", "condition", "value"}),
                permissions=frozenset({"spreadsheet.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.calculate",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 with hash-checks: calling every spreadsheet mutator with output == source returns success=False and the error 'Output must not overwrite the source artifact.' The guard is structural (_resolve_output compares abspath(source) to abspath(destination) and raises), and the default destination is a sibling '<stem>_<op><ext>' with a numeric counter on collision. Verified individually for add_column, update_cell, sort, filter_rows, calculate, rank, group_by and aggregate -- the group is uniform here, each routed through the same _resolve_output helper."),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.calculate",
                description="Add a calculated column to a spreadsheet.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path", "sheet_name", "formula_column", "formula_template"}),
                permissions=frozenset({"spreadsheet.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.rank",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 with hash-checks: calling every spreadsheet mutator with output == source returns success=False and the error 'Output must not overwrite the source artifact.' The guard is structural (_resolve_output compares abspath(source) to abspath(destination) and raises), and the default destination is a sibling '<stem>_<op><ext>' with a numeric counter on collision. Verified individually for add_column, update_cell, sort, filter_rows, calculate, rank, group_by and aggregate -- the group is uniform here, each routed through the same _resolve_output helper."),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.rank",
                description="Add a rank column to a spreadsheet.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path", "sheet_name", "rank_column"}),
                permissions=frozenset({"spreadsheet.write"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.group_by",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 with hash-checks: calling every spreadsheet mutator with output == source returns success=False and the error 'Output must not overwrite the source artifact.' The guard is structural (_resolve_output compares abspath(source) to abspath(destination) and raises), and the default destination is a sibling '<stem>_<op><ext>' with a numeric counter on collision. Verified individually for add_column, update_cell, sort, filter_rows, calculate, rank, group_by and aggregate -- the group is uniform here, each routed through the same _resolve_output helper."),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.group_by",
                description="Group and aggregate spreadsheet rows.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path", "sheet_name", "column"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.aggregate",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("VERIFIED 2026-10-07 with hash-checks: calling every spreadsheet mutator with output == source returns success=False and the error 'Output must not overwrite the source artifact.' The guard is structural (_resolve_output compares abspath(source) to abspath(destination) and raises), and the default destination is a sibling '<stem>_<op><ext>' with a numeric counter on collision. Verified individually for add_column, update_cell, sort, filter_rows, calculate, rank, group_by and aggregate -- the group is uniform here, each routed through the same _resolve_output helper."),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.aggregate",
                description="Aggregate spreadsheet columns.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path", "sheet_name", "columns"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=90,
            ),
            CapabilityDescriptor(
                capability_id="spreadsheet.compare",
                blast_radius=BlastRadius.REVERSIBLE_LOCAL,
                blast_radius_reason=('Reads or compares spreadsheet data without modifying it.'),
                category=CapabilityCategory.DATA,
                operation="spreadsheet.compare",
                description="Compare two spreadsheets.",
                provider="genesis.sheet_intel",
                supported_inputs=frozenset({"path1", "sheet1", "path2", "sheet2"}),
                permissions=frozenset({"spreadsheet.read"}),
                priority=90,
            ),
        )

        for capability in builtins:
            cls.register(
                capability,
                replace=True,
            )

    # ============================================================
# MODULE INITIALIZATION
# ============================================================
#
# The legacy Level 3 architecture expects the capability
# catalog to exist as soon as CapabilityRegistry is imported.
#
# This preserves that behavior while allowing Level 3.8 to
# extend the registry later.

    @classmethod
    def _assert_builtin_integrity(cls) -> None:
        """
        Internal development invariant.

        The established Level 3 application surface must exist
        before any execution/safety layer can use the registry.
        """

        required = {
            "application.open",
                "application.inspect",
            "application.list",
        }

        missing = (
            required
            - set(cls.operations())
        )

        if missing:
            raise CapabilityRegistryError(
                "Capability registry initialization incomplete. "
                f"Missing: {sorted(missing)}"
            )

    @classmethod
    def _register_catalog_gap_capabilities(cls) -> None:
        category_map = {
            "application": CapabilityCategory.APPLICATION,
            "browser": CapabilityCategory.BROWSER,
            "data": CapabilityCategory.DATA,
            "document": CapabilityCategory.DOCUMENT,
            "file": CapabilityCategory.FILESYSTEM,
            "filesystem": CapabilityCategory.FILESYSTEM,
            "folder": CapabilityCategory.FILESYSTEM,
            "gui": CapabilityCategory.ACCESSIBILITY,
            "spreadsheet": CapabilityCategory.DATA,
        }
        for capability_id in sorted(CAPABILITIES):
            if capability_id in cls._capabilities:
                continue
            alias = ALIASES.get(capability_id)
            if alias and alias in cls._capabilities:
                descriptor = replace(
                    cls._capabilities[alias],
                    capability_id=capability_id,
                    operation=capability_id,
                    description=f"Compatibility capability for {alias}.",
                )
            else:
                prefix = capability_id.split(".", 1)[0]
                category = category_map.get(prefix, CapabilityCategory.GENERAL)
                provider = f"genesis.{prefix}"
                # Catalog-gap capabilities are auto-generated placeholders:
                # the id is known to the catalog but nobody hand-wrote a
                # descriptor for it. They previously inherited the
                # blast-radius default silently, which is exactly the
                # failure the field exists to prevent — a capability
                # nobody classified would ship as a decision nobody made.
                # The classification is therefore stated explicitly here,
                # including for ids with no known semantics, which stay
                # denied rather than defaulting to open.
                tier, reason = _CATALOG_GAP_CLASSIFICATION.get(
                    capability_id,
                    (
                        BlastRadius.IRREVERSIBLE_OR_OUTWARD,
                        "Catalog-gap capability: the id is registered in "
                        "capability_catalog.CAPABILITIES but has no "
                        "hand-written descriptor, so its semantics are "
                        "unreviewed. Denied by default rather than "
                        "silently inheriting a permissive tier.",
                    ),
                )
                descriptor = CapabilityDescriptor(
                    capability_id=capability_id,
                    blast_radius=tier,
                    blast_radius_reason=reason,
                    category=category,
                    operation=capability_id,
                    description=f"Execute the {capability_id} capability through the authoritative provider boundary.",
                    provider=provider,
                    supported_inputs=frozenset({"path", "target", "query", "text"}),
                    permissions=frozenset(),
                    priority=50,
                )
            cls.register(descriptor, replace=True)

    @staticmethod
    def _descriptor_to_dict(
        capability: CapabilityDescriptor,
    ) -> Dict[str, Any]:

        return capability.to_dict()
    # ============================================================
# MODULE-LEVEL REGISTRY INITIALIZATION
# ============================================================
# ============================================================
# MODULE-LEVEL REGISTRY INITIALIZATION
# ============================================================

def _initialize_capability_registry() -> None:
    """
    Initialize the canonical Genesis capability catalog.

    This executes only after CapabilityRegistry has been
    completely created by Python.
    """

    CapabilityRegistry._register_builtin_capabilities()
    CapabilityRegistry._register_catalog_gap_capabilities()
    CapabilityRegistry._assert_builtin_integrity()


_initialize_capability_registry()

    