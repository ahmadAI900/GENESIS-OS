"""
Genesis OS — Level 3 Security Model.

Capability/Risk Framework for computer operations:

    read-only        → Low risk, auto-allowed
    reversible       → Low risk, auto-allowed
    modifying        → Medium risk, confirmation-gated
    destructive      → High risk, confirmation + verification required
    security-sensitive → High risk, explicit authorization required
    external-side-effect → High risk, explicit authorization required

This provides the architectural foundation for permission management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple


class RiskLevel(Enum):
    """Risk classification for operations."""
    LOW = "low"           # Read-only, safe to auto-execute
    MEDIUM = "medium"     # Modifying, confirmation-gated
    HIGH = "high"         # Destructive, security-sensitive, explicit auth required


class OperationCategory(Enum):
    """Category of operation for risk assessment."""
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    MODIFYING = "modifying"
    DESTRUCTIVE = "destructive"
    SECURITY_SENSITIVE = "security_sensitive"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


@dataclass(frozen=True)
class RiskAssessment:
    """Risk assessment for an operation."""
    operation: str
    risk_level: RiskLevel
    category: OperationCategory
    requires_confirmation: bool
    requires_verification: bool
    requires_explicit_auth: bool
    reason: str
    mitigations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Permission:
    """A permission grant or denial."""
    permission_id: str
    description: str
    risk_level: RiskLevel
    granted: bool = False
    conditions: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[str] = None  # ISO timestamp


class CapabilityRiskProfile:
    """
    Defines the risk profile for a capability.
    
    Each registered capability has an associated risk profile
    that determines how it should be handled.
    """

    # Default risk profiles for known capabilities
    DEFAULT_PROFILES: Dict[str, RiskAssessment] = {
        # Low risk - read only
        "application.inspect": RiskAssessment(
            operation="application.inspect",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only reads application state, no modifications",
        ),
        "application.list": RiskAssessment(
            operation="application.list",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only lists installed applications",
        ),
        "file.inspect": RiskAssessment(
            operation="file.inspect",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only reads file metadata",
        ),
        "file.read": RiskAssessment(
            operation="file.read",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only reads file content",
        ),
        "file.search": RiskAssessment(
            operation="file.search",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only searches for files",
        ),
        "file.hash": RiskAssessment(
            operation="file.hash",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only computes file hash",
        ),
        "folder.inspect": RiskAssessment(
            operation="folder.inspect",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only reads folder metadata",
        ),
        "browser.search": RiskAssessment(
            operation="browser.search",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only searches the web",
        ),
        # ``browser.click`` is a non-destructive web-page
        # interaction.  It was missing from the risk profile
        # table, so the security model fell back to the
        # "unknown operation" default which flagged it as
        # HIGH / requires_explicit_auth=True.  That made
        # the agent-framework adapter's tool unusable even
        # though the underlying click action is benign.
        # Phase 2 Session B added the missing entry (LOW,
        # READ_ONLY, no confirmation) so the executor's
        # confirmation gate stops blocking the call and the
        # honest-fallback ``verified=False`` from
        # ``verify_browser_click`` surfaces to the model
        # directly.
        "browser.click": RiskAssessment(
            operation="browser.click",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason=(
                "Clicks an element in the live web page "
                "(non-destructive; honest-fallback "
                "verified=False until the underlying "
                "provider gains a real element_found "
                "post-state signal)"
            ),
        ),
        "system.status": RiskAssessment(
            operation="system.status",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only reads system status",
        ),
        "process.list": RiskAssessment(
            operation="process.list",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only lists processes",
        ),
        "process.inspect": RiskAssessment(
            operation="process.inspect",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only inspects process state",
        ),
        "network.list_wifi": RiskAssessment(
            operation="network.list_wifi",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Only lists Wi-Fi networks",
        ),

        # Medium risk - reversible modifications
        "application.open": RiskAssessment(
            operation="application.open",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.REVERSIBLE,
            requires_confirmation=False,  # Common operation
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Launches application (reversible by closing)",
        ),
        "application.close": RiskAssessment(
            operation="application.close",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.REVERSIBLE,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Closes application (reversible by reopening)",
        ),
        "file.open": RiskAssessment(
            operation="file.open",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.REVERSIBLE,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Opens file with default app (reversible)",
        ),
        "folder.open": RiskAssessment(
            operation="folder.open",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.REVERSIBLE,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Opens folder in explorer (reversible)",
        ),
        "browser.open_url": RiskAssessment(
            operation="browser.open_url",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.REVERSIBLE,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Opens URL in browser (reversible by closing tab)",
        ),
        "browser.select": RiskAssessment(
            operation="browser.select",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.REVERSIBLE,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Selects dropdown option (reversible by re-selecting)",
        ),
        "browser.download": RiskAssessment(
            operation="browser.download",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Downloads file from URL and writes it to the filesystem",
            mitigations=("Path validation", "URL validation", "Explicit approval"),
        ),
        "browser.upload": RiskAssessment(
            operation="browser.upload",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.EXTERNAL_SIDE_EFFECT,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Uploads a local file to a remote web form",
            mitigations=("File existence check", "Path validation", "Explicit approval"),
        ),
        "document.edit": RiskAssessment(
            operation="document.edit",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Edits document content and may create a derived artifact",
            mitigations=("Content validation", "Output path validation", "Explicit approval"),
        ),
        "document.transform": RiskAssessment(
            operation="document.transform",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Transforms a document into a new format",
            mitigations=("Output path validation", "Format validation", "Explicit approval"),
        ),
        "document.verify": RiskAssessment(
            operation="document.verify",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Verifies document state (read-only operation)",
        ),

        # Medium-High risk - modifying
        "file.create": RiskAssessment(
            operation="file.create",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Creates new file (modifies filesystem)",
            mitigations=("Overwrite protection", "Path validation"),
        ),
        "file.copy": RiskAssessment(
            operation="file.copy",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Copies file (modifies destination)",
            mitigations=("Destination validation", "Overwrite confirmation"),
        ),
        "file.move": RiskAssessment(
            operation="file.move",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Moves file (modifies source and destination)",
            mitigations=("Destination validation", "Source preservation"),
        ),
        "file.rename": RiskAssessment(
            operation="file.rename",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Renames file (modifies filesystem)",
            mitigations=("Name validation", "Collision check"),
        ),
        "folder.create": RiskAssessment(
            operation="folder.create",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Creates folder (modifies filesystem)",
        ),
        "folder.rename": RiskAssessment(
            operation="folder.rename",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Renames folder (modifies filesystem)",
        ),
        "folder.move": RiskAssessment(
            operation="folder.move",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Moves folder (modifies filesystem)",
        ),
        "folder.organize": RiskAssessment(
            operation="folder.organize",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Organizes folder contents (modifies many files)",
        ),
        "spreadsheet.sort": RiskAssessment(
            operation="spreadsheet.sort",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Modifies spreadsheet data order",
        ),
        "document.create_docx": RiskAssessment(
            operation="document.create_docx",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Creates document file (modifies filesystem)",
        ),
        "clipboard.copy": RiskAssessment(
            operation="clipboard.copy",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,  # Low impact
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Writes to clipboard (overwrites previous)",
        ),
        "gui.focus_window": RiskAssessment(
            operation="gui.focus_window",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Focuses an existing window without changing application data",
        ),
        "gui.inspect_window": RiskAssessment(
            operation="gui.inspect_window",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Reads window metadata",
        ),
        "gui.read_visible_text": RiskAssessment(
            operation="gui.read_visible_text",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Reads visible text from the focused window",
        ),
        "gui.inspect_ui_tree": RiskAssessment(
            operation="gui.inspect_ui_tree",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Reads the accessibility tree",
        ),
        "gui.type_text": RiskAssessment(
            operation="gui.type_text",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Types user-provided text into an explicitly authorized focused window",
        ),
        "gui.paste_text": RiskAssessment(
            operation="gui.paste_text",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Pastes user-provided text into an explicitly authorized focused window",
        ),
        "gui.click": RiskAssessment(
            operation="gui.click",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Clicks a UI element within the resolved target",
        ),
        "gui.double_click": RiskAssessment(
            operation="gui.double_click",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Double-clicks a UI element within the resolved target",
        ),
        "gui.select": RiskAssessment(
            operation="gui.select",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Selects a UI option within the resolved target",
        ),
        "gui.scroll": RiskAssessment(
            operation="gui.scroll",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Scrolls the resolved view without changing data",
        ),
        "gui.keyboard_action": RiskAssessment(
            operation="gui.keyboard_action",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Sends a keyboard action to the explicitly resolved foreground target",
        ),
        "gui.hotkey": RiskAssessment(
            operation="gui.hotkey",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Sends a keyboard shortcut that may change application state",
        ),
        "gui.drag": RiskAssessment(
            operation="gui.drag",
            risk_level=RiskLevel.MEDIUM,
            category=OperationCategory.MODIFYING,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Moves a UI element and may change application state",
        ),
        "gui.wait": RiskAssessment(
            operation="gui.wait",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Waits for a UI state without changing data",
        ),
        "gui.wait_for_window": RiskAssessment(
            operation="gui.wait_for_window",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Waits for a window to appear without changing data",
        ),
        "gui.wait_for_state": RiskAssessment(
            operation="gui.wait_for_state",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Waits for a UI state without changing data",
        ),

        # High risk - destructive
        "file.delete": RiskAssessment(
            operation="file.delete",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.DESTRUCTIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Permanently deletes file",
            mitigations=("Recycle bin support", "Explicit confirmation", "Path validation"),
        ),
        "folder.delete": RiskAssessment(
            operation="folder.delete",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.DESTRUCTIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Permanently deletes folder and contents",
            mitigations=("Recycle bin support", "Explicit confirmation", "Empty folder check"),
        ),
        "network.connect_wifi": RiskAssessment(
            operation="network.connect_wifi",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Modifies network configuration with credentials",
            mitigations=("Credential protection", "Connection verification"),
        ),

        # High risk - security sensitive
        "system.open_settings": RiskAssessment(
            operation="system.open_settings",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Opens system settings (potential security changes)",
        ),
        "workstation.lock": RiskAssessment(
            operation="workstation.lock",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Locks workstation (interrupts user session)",
        ),
        "package.install": RiskAssessment(
            operation="package.install",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Installs software (system modification)",
            mitigations=("Source verification", "Signature check", "Explicit approval"),
        ),
        "package.uninstall": RiskAssessment(
            operation="package.uninstall",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Removes software (system modification)",
        ),
        "cleanup.empty_recycle_bin": RiskAssessment(
            operation="cleanup.empty_recycle_bin",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.DESTRUCTIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Permanently deletes all recycled items",
            mitigations=("Final confirmation", "Item count preview"),
        ),
        # Level 3.11 - Web research
        "web.research": RiskAssessment(
            operation="web.research",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Searches the live web and returns structured results (read-only)",
        ),
        # Level 3.12 - Package management
        "package.search": RiskAssessment(
            operation="package.search",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Searches package repositories (read-only)",
        ),
        "package.install": RiskAssessment(
            operation="package.install",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Installs software (system modification)",
            mitigations=("Source verification", "Signature check", "Explicit approval"),
        ),
        "package.uninstall": RiskAssessment(
            operation="package.uninstall",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Removes software (system modification)",
        ),
        # Level 3.12 - Cleanup
        "cleanup.recycle_bin_query": RiskAssessment(
            operation="cleanup.recycle_bin_query",
            risk_level=RiskLevel.LOW,
            category=OperationCategory.READ_ONLY,
            requires_confirmation=False,
            requires_verification=True,
            requires_explicit_auth=False,
            reason="Queries Recycle Bin contents (read-only)",
        ),
        "cleanup.empty_recycle_bin": RiskAssessment(
            operation="cleanup.empty_recycle_bin",
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.DESTRUCTIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Permanently deletes all recycled items",
            mitigations=("Final confirmation", "Item count preview"),
        ),
    }


class SecurityManager:
    """
    Central security manager for Genesis OS operations.

    Evaluates risk, enforces permissions, and manages confirmation flow.
    """

    _MEDIUM_CONFIRMATION_REQUIRED = frozenset({
        "browser.download",
        "browser.upload",
        "clipboard.paste",
        "data.transform",
        "display.brightness_set",
        "document.create",
        "document.create_csv",
        "document.create_docx",
        "document.create_json",
        "document.create_markdown",
        "document.create_pdf",
        "document.create_txt",
        "notes.create",
        "screen.capture",
        "spreadsheet.add_column",
        "spreadsheet.aggregate",
        "spreadsheet.calculate",
        "spreadsheet.create_from_dicts",
        "spreadsheet.filter",
        "spreadsheet.group_by",
        "spreadsheet.rank",
        "spreadsheet.update_cell",
        "volume.down",
        "volume.mute_toggle",
        "volume.set",
        "volume.up",
    })

    VERSION = "3.0.0"

    def __init__(self):
        self._profiles: Dict[str, RiskAssessment] = dict(CapabilityRiskProfile.DEFAULT_PROFILES)
        self._permissions: Dict[str, Permission] = {}
        self._custom_profiles: Dict[str, RiskAssessment] = {}

    def register_profile(self, operation: str, assessment: RiskAssessment) -> None:
        """Register a custom risk profile for an operation."""
        self._custom_profiles[operation] = assessment

    def get_assessment(self, operation: str) -> RiskAssessment:
        """Get the risk assessment for an operation."""
        if operation in self._custom_profiles:
            return self._custom_profiles[operation]
        assessment = self._profiles.get(operation)
        if assessment is not None:
            return assessment
        try:
            from genesis_os.capability_catalog import canonical_id
            canonical = canonical_id(operation)
        except Exception:
            canonical = operation
        assessment = self._profiles.get(canonical)
        if assessment is not None:
            return assessment
        return self._descriptor_assessment(operation)

    def _descriptor_assessment(self, operation: str) -> RiskAssessment:
        try:
            from genesis_os.capability_catalog import canonical_id
            from genesis_os.capability_registry import CapabilityRegistry
            canonical = canonical_id(operation)
            descriptor = CapabilityRegistry.get(canonical)
        except Exception:
            return self._default_assessment(operation)
        risk_name = str(
            getattr(descriptor, "risk_level", "low")
        ).strip().lower()
        if risk_name == "low":
            risk_level = RiskLevel.LOW
            category = OperationCategory.READ_ONLY
            requires_confirmation = False
            requires_explicit_auth = False
        elif risk_name == "medium":
            risk_level = RiskLevel.MEDIUM
            category = OperationCategory.MODIFYING
            requires_confirmation = (
                canonical in self._MEDIUM_CONFIRMATION_REQUIRED
            )
            requires_explicit_auth = False
        else:
            risk_level = RiskLevel.HIGH
            category = OperationCategory.SECURITY_SENSITIVE
            requires_confirmation = True
            requires_explicit_auth = True
        if canonical in {
            "browser.upload",
            "network.connect_wifi",
        }:
            category = OperationCategory.EXTERNAL_SIDE_EFFECT
        return RiskAssessment(
            operation=operation,
            risk_level=risk_level,
            category=category,
            requires_confirmation=requires_confirmation,
            requires_verification=True,
            requires_explicit_auth=requires_explicit_auth,
            reason=(
                f"Capability descriptor classification for "
                f"{canonical} ({risk_name})"
            ),
        )

    def _default_assessment(self, operation: str) -> RiskAssessment:
        """Generate a default assessment for unknown operations."""
        return RiskAssessment(
            operation=operation,
            risk_level=RiskLevel.HIGH,
            category=OperationCategory.SECURITY_SENSITIVE,
            requires_confirmation=True,
            requires_verification=True,
            requires_explicit_auth=True,
            reason="Unknown operation - defaulting to maximum caution",
        )

    def evaluate(self, operation: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluate an operation for security compliance.
        
        Returns a decision object with:
        - allowed: bool
        - risk_level: RiskLevel
        - requires_confirmation: bool
        - requires_verification: bool
        - requires_explicit_auth: bool
        - reason: str
        - mitigations: tuple
        """
        assessment = self.get_assessment(operation)

        # Check if permission is explicitly granted
        permission = self._permissions.get(operation)
        if permission and permission.granted:
            # Permission granted, but still enforce verification
            return {
                "allowed": True,
                "risk_level": assessment.risk_level.value,
                "category": assessment.category.value,
                "requires_confirmation": assessment.requires_confirmation,
                "requires_verification": assessment.requires_verification,
                "requires_explicit_auth": False,  # Permission overrides auth requirement
                "reason": assessment.reason,
                "mitigations": assessment.mitigations,
                "permission_granted": True,
            }

        # For low risk, auto-allow
        if assessment.risk_level == RiskLevel.LOW:
            return {
                "allowed": True,
                "risk_level": assessment.risk_level.value,
                "category": assessment.category.value,
                "requires_confirmation": False,
                "requires_verification": assessment.requires_verification,
                "requires_explicit_auth": False,
                "reason": assessment.reason,
                "mitigations": assessment.mitigations,
            }

        # For medium risk, allow with confirmation requirement
        if assessment.risk_level == RiskLevel.MEDIUM:
            return {
                "allowed": True,
                "risk_level": assessment.risk_level.value,
                "category": assessment.category.value,
                "requires_confirmation": assessment.requires_confirmation,
                "requires_verification": assessment.requires_verification,
                "requires_explicit_auth": False,
                "reason": assessment.reason,
                "mitigations": assessment.mitigations,
            }

        # For high risk, require explicit authorization
        return {
            "allowed": True,  # Allowed but gated
            "risk_level": assessment.risk_level.value,
            "category": assessment.category.value,
            "requires_confirmation": assessment.requires_confirmation,
            "requires_verification": assessment.requires_verification,
            "requires_explicit_auth": assessment.requires_explicit_auth,
            "reason": assessment.reason,
            "mitigations": assessment.mitigations,
        }

    def grant_permission(self, operation: str, conditions: Optional[Dict[str, Any]] = None) -> Permission:
        """Grant a permission for an operation."""
        assessment = self.get_assessment(operation)
        permission = Permission(
            permission_id=f"perm-{operation}",
            description=f"Permission for {operation}",
            risk_level=assessment.risk_level,
            granted=True,
            conditions=conditions or {},
        )
        self._permissions[operation] = permission
        return permission

    def revoke_permission(self, operation: str) -> bool:
        """Revoke a granted permission."""
        if operation in self._permissions:
            del self._permissions[operation]
            return True
        return False

    def check_confirmation_required(self, operation: str) -> bool:
        """Check if an operation requires user confirmation."""
        assessment = self.get_assessment(operation)
        return assessment.requires_confirmation

    def check_verification_required(self, operation: str) -> bool:
        """Check if an operation requires post-execution verification."""
        assessment = self.get_assessment(operation)
        return assessment.requires_verification

    def check_explicit_auth_required(self, operation: str) -> bool:
        """Check if an operation requires explicit authorization."""
        assessment = self.get_assessment(operation)
        return assessment.requires_explicit_auth

    def get_all_assessments(self) -> Dict[str, RiskAssessment]:
        """Get all registered risk assessments."""
        return {**self._profiles, **self._custom_profiles}

    def get_operations_by_risk(self, risk_level: RiskLevel) -> List[str]:
        """Get all operations with a specific risk level."""
        return [
            op for op, assessment in self.get_all_assessments().items()
            if assessment.risk_level == risk_level
        ]


# Integration with ActionExecutor
class SecureActionExecutor:
    """
    Wrapper that adds security evaluation to action execution.
    
    This can be used to add security checks before execution.
    """

    def __init__(self, executor, security_manager: Optional[SecurityManager] = None):
        self.executor = executor
        self.security = security_manager or SecurityManager()

    def execute(self, plan) -> Any:
        """Execute with security evaluation."""
        # Evaluate security
        evaluation = self.security.evaluate(plan.operation)

        # Add security metadata to plan
        if hasattr(plan, 'parameters') and plan.parameters is not None:
            plan.parameters["_security_evaluation"] = evaluation

        # Execute
        return self.executor.execute(plan)


# Convenience functions
def assess_operation_risk(
    operation: str,
    context: Optional[Dict[str, Any]] = None,
) -> RiskAssessment:
    """Quick function to assess operation risk.

    For browser.click, this applies a lightweight heuristic: if the
    element text, alt-text, or ARIA label contains high-risk signal
    words (e.g. "delete", "remove", "buy", "purchase", "send",
    "confirm", "pay", "unsubscribe"), the click is flagged as
    requiring confirmation.

    For image/icon elements where no accessible text is available
    at all, the heuristic flags the element as unassessable and
    defaults to requiring confirmation — matching the roadmap's
    "real state over assumptions" principle.

    This is a heuristic safety net, not a complete risk assessment.
    """
    manager = SecurityManager()

    # For browser.click, apply heuristic signal-word check
    if operation == "browser.click" and context:
        # Check all accessible text sources: inner text, alt-text,
        # and aria-label.  Same signal-word list, different source
        # fields — covers image/icon elements that have no inner
        # text but do have alt or aria attributes.
        def _safe_str(val):
            if isinstance(val, str):
                return val
            return ""

        accessible_text = " ".join(
            filter(None, [
                _safe_str(context.get("element_text", "")),
                _safe_str(context.get("alt_text", "")),
                _safe_str(context.get("aria_label", "")),
            ])
        ).lower()

        # The signal list and its detection now live in
        # genesis_os.blast_radius, which also registers the
        # browser.click dynamic evaluator built on top of them. This
        # module keeps constructing its own RiskAssessment (the
        # executor consumes that shape), but there is exactly one
        # definition of what counts as a high-risk signal.
        from .blast_radius import click_risk_signal

        signal = click_risk_signal(accessible_text)

        if signal:
            return RiskAssessment(
                operation=operation,
                risk_level=RiskLevel.HIGH,
                category=OperationCategory.EXTERNAL_SIDE_EFFECT,
                requires_confirmation=True,
                requires_verification=True,
                requires_explicit_auth=False,
                reason=(
                    f"browser.click on element with high-risk signal "
                    f"text '{signal}' — heuristic safety net "
                    f"(Phase 8 Browser Intelligence provides "
                    f"real post-state verification)"
                ),
            )

        # No accessible text at all — element is unassessable.
        # This covers: image/icon buttons with no alt/aria, dynamic
        # content rendered by JavaScript with no accessible source,
        # shadow DOM elements with no exposed text.  Default to
        # requiring confirmation when uncertain, per the roadmap's
        # "real state over assumptions" principle.
        no_text = bool(context.get("_no_element_text", False))
        if no_text and not accessible_text:
            return RiskAssessment(
                operation=operation,
                risk_level=RiskLevel.MEDIUM,
                category=OperationCategory.MODIFYING,
                requires_confirmation=True,
                requires_verification=True,
                requires_explicit_auth=False,
                reason=(
                    "browser.click on element with no accessible text "
                    "(image/icon/dynamic content) — unassessable risk, "
                    "defaulting to confirmation required"
                ),
            )

    return manager.get_assessment(operation)


def is_operation_high_risk(operation: str) -> bool:
    """Quick check if operation is high risk."""
    manager = SecurityManager()
    assessment = manager.get_assessment(operation)
    return assessment.risk_level == RiskLevel.HIGH


def requires_confirmation(operation: str) -> bool:
    """Quick check if operation requires confirmation."""
    manager = SecurityManager()
    return manager.check_confirmation_required(operation)


def requires_verification(operation: str) -> bool:
    """Quick check if operation requires verification."""
    manager = SecurityManager()
    return manager.check_verification_required(operation)