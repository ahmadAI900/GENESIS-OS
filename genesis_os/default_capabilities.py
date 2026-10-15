"""
Genesis OS — Level 3.8.6
Default Capability Definitions.

This module registers Genesis's built-in capability
descriptors.

Important:
    These descriptors describe available capabilities.
    They do not execute operating-system actions.

Execution remains owned by the appropriate subsystem.
"""

from .capabilities import (
    BlastRadius,
    CapabilityCategory,
    CapabilityDescriptor,
)

from .capability_registry import (
    CapabilityRegistry,
)


def register_default_capabilities(
    registry: CapabilityRegistry,
) -> None:
    """
    Register Genesis's built-in capabilities.

    Registration is idempotent because capabilities are
    registered with replace=True.
    """

    capabilities = (
        CapabilityDescriptor(
            capability_id="filesystem.search",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Reads file state, contents, hashes or search results.'),
            category=CapabilityCategory.FILESYSTEM,
            operation="search",
            description=(
                "Search accessible filesystem locations "
                "for matching targets."
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
            operation="open",
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
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="application.launch",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("Launching an app is undone by closing it; no user data "
                                 "destroyed. Same reversibility as application.open, which "
                                 "it duplicates under a different operation id."),
            category=CapabilityCategory.APPLICATION,
            operation="launch",
            description=(
                "Launch a resolved application."
            ),
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
            capability_id="application.close",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Closing loses unsaved work, which is irreversible. Kept reversible_local ONLY because the existing unsaved-changes precondition already escalates it; see OPEN QUESTION 1 in the classification report.'),
            category=CapabilityCategory.APPLICATION,
            operation="close",
            description=(
                "Close a running application."
            ),
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
            capability_id="document.read",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Comparison and inspection are read-only.'),
            category=CapabilityCategory.DOCUMENT,
            operation="read",
            description=(
                "Read supported document content."
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

        CapabilityDescriptor(
            capability_id="data.inspect",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Inspects data without modifying it.'),
            category=CapabilityCategory.DATA,
            operation="inspect",
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
            operation="transform",
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

        # -----------------------------------------------------
        # PHASE 6 — GUI INTERACTION CAPABILITIES
        # -----------------------------------------------------

        CapabilityDescriptor(
            capability_id="gui.click",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
            category=CapabilityCategory.APPLICATION,
            operation="click",
            description=(
                "Click at coordinates or a semantic UI target."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "x", "y", "target",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.double_click",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
            category=CapabilityCategory.APPLICATION,
            operation="double_click",
            description=(
                "Double-click at coordinates or a semantic UI target."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "x", "y", "target",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.type_text",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('FORK DECISION 1: typing into local UI state is itself reversible. Outward effects occur at a subsequent send/submit action, which must independently default to irreversible_or_outward.'),
            category=CapabilityCategory.APPLICATION,
            operation="type_text",
            description=(
                "Type text into the focused window or a named target."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "text", "focus_title_pattern",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.paste_text",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('FORK DECISION 1: typing into local UI state is itself reversible. Outward effects occur at a subsequent send/submit action, which must independently default to irreversible_or_outward.'),
            category=CapabilityCategory.APPLICATION,
            operation="paste_text",
            description=(
                "Paste text from clipboard into the focused window."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "text", "focus_title_pattern",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.hotkey",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
            category=CapabilityCategory.APPLICATION,
            operation="hotkey",
            description=(
                "Send a keyboard hotkey combination (e.g. Ctrl+S)."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "keys",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.drag",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
            category=CapabilityCategory.APPLICATION,
            operation="drag",
            description=(
                "Drag from one position to another."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "start_x", "start_y", "end_x", "end_y",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.scroll",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Reads or inspects UI state without modifying it.'),
            category=CapabilityCategory.APPLICATION,
            operation="scroll",
            description=(
                "Scroll the focused window or a target element."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "direction", "amount",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.keyboard_action",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=("Drives local UI state reversibly, but the same dynamic-signal question as browser.click applies: clicking a 'Delete' button in a third-party app is not reversible. See OPEN QUESTION 5."),
            category=CapabilityCategory.APPLICATION,
            operation="keyboard_action",
            description=(
                "Send a single key press or key combination."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "key",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.select",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Reads or inspects UI state without modifying it.'),
            category=CapabilityCategory.APPLICATION,
            operation="select",
            description=(
                "Select text or a UI element."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "start", "end", "target",
            }),
            permissions=frozenset({
                "gui.interact",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.wait_for_window",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Reads or inspects UI state without modifying it.'),
            category=CapabilityCategory.APPLICATION,
            operation="wait_for_window",
            description=(
                "Wait for a window matching a pattern to appear."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "title_pattern", "timeout",
            }),
            permissions=frozenset({
                "gui.observe",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="gui.inspect_ui_tree",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Reads or inspects UI state without modifying it.'),
            category=CapabilityCategory.APPLICATION,
            operation="inspect_ui_tree",
            description=(
                "Inspect UI elements of a window using accessibility APIs."
            ),
            provider="genesis.gui",
            supported_inputs=frozenset({
                "title_pattern",
            }),
            permissions=frozenset({
                "gui.observe",
            }),
            priority=100,
        ),

        CapabilityDescriptor(
            capability_id="application.focus",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Focus can be moved elsewhere; no persistent state changes.'),
            category=CapabilityCategory.APPLICATION,
            operation="focus",
            description=(
                "Focus a running application window."
            ),
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
            capability_id="application.window_list",
            blast_radius=BlastRadius.REVERSIBLE_LOCAL,
            blast_radius_reason=('Reads process/window state; changes nothing.'),
            category=CapabilityCategory.APPLICATION,
            operation="window_list",
            description=(
                "List all visible windows with metadata."
            ),
            provider="genesis.application",
            supported_inputs=frozenset(),
            permissions=frozenset({
                "gui.observe",
            }),
            priority=100,
        ),
    )

    for capability in capabilities:
        registry.register(
            capability,
            replace=True,
        )