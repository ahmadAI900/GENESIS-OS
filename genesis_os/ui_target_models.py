"""
Genesis OS — Phase 6 UI Target Model.

Generalized UI target abstraction for semantic interaction.

Targets may represent buttons, text fields, editors, checkboxes,
menus, list items, and other UI controls. Resolution supports
semantic properties like automation ID, name, control type, and
parent context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class UIControlType(str, Enum):
    """Standard UI Automation control types."""
    BUTTON = "button"
    TEXT = "text"
    EDIT = "edit"
    CHECKBOX = "checkbox"
    RADIO_BUTTON = "radio_button"
    COMBO_BOX = "combo_box"
    LIST = "list"
    LIST_ITEM = "list_item"
    MENU = "menu"
    MENU_ITEM = "menu_item"
    TAB = "tab"
    TAB_ITEM = "tab_item"
    TREE = "tree"
    TREE_ITEM = "tree_item"
    TOOLBAR = "toolbar"
    WINDOW = "window"
    PANE = "pane"
    DOCUMENT = "document"
    DATA_GRID = "data_grid"
    GROUP = "group"
    HYPERLINK = "hyperlink"
    IMAGE = "image"
    SLIDER = "slider"
    SPINNER = "spinner"
    STATUS_BAR = "status_bar"
    THUMB = "thumb"
    TITLE_BAR = "title_bar"
    TOOL_TIP = "tool_tip"
    UNKNOWN = "unknown"


class UITargetConfidence(str, Enum):
    """Confidence levels for UI target resolution."""
    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class UITarget:
    """
    A resolved UI element target.

    Contains all information needed to perform a GUI action
    on a specific UI element.
    """
    name: str = ""
    automation_id: str = ""
    control_type: UIControlType = UIControlType.UNKNOWN
    class_name: str = ""
    value: str = ""
    text: str = ""

    hwnd: int = 0
    process_id: Optional[int] = None

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    is_enabled: bool = True
    is_visible: bool = True
    is_focusable: bool = True

    patterns: List[str] = field(default_factory=list)

    confidence: UITargetConfidence = UITargetConfidence.NONE
    resolution_method: str = ""
    alternatives: List["UITarget"] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "automation_id": self.automation_id,
            "control_type": self.control_type.value,
            "class_name": self.class_name,
            "value": self.value,
            "text": self.text,
            "bounds": {
                "left": self.left,
                "top": self.top,
                "right": self.right,
                "bottom": self.bottom,
                "center_x": self.center_x,
                "center_y": self.center_y,
            },
            "is_enabled": self.is_enabled,
            "is_visible": self.is_visible,
            "is_focusable": self.is_focusable,
            "patterns": list(self.patterns),
            "confidence": self.confidence.value,
            "resolution_method": self.resolution_method,
        }
        if self.alternatives:
            result["alternatives"] = [a.to_dict() for a in self.alternatives]
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass
class UITargetResolution:
    """
    Result of UI target resolution.

    Contains the resolved target (if any) and evidence
    about the resolution process.
    """
    target: Optional[UITarget] = None
    resolved: bool = False
    ambiguous: bool = False
    unsupported: bool = False
    error: Optional[str] = None
    candidates: List[UITarget] = field(default_factory=list)
    resolution_method: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "resolved": self.resolved,
            "ambiguous": self.ambiguous,
            "unsupported": self.unsupported,
        }
        if self.target:
            result["target"] = self.target.to_dict()
        if self.error:
            result["error"] = self.error
        if self.candidates:
            result["candidates"] = [c.to_dict() for c in self.candidates]
        if self.resolution_method:
            result["resolution_method"] = self.resolution_method
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


# Canonical key names for normalization
_KEY_ALIASES: Dict[str, List[str]] = {
    "enter": ["enter", "return", "↵"],
    "escape": ["escape", "esc"],
    "tab": ["tab", "⇥"],
    "backspace": ["backspace", "back"],
    "delete": ["delete", "del"],
    "home": ["home"],
    "end": ["end"],
    "pageup": ["pageup", "page_up", "pgup"],
    "pagedown": ["pagedown", "page_down", "pgdn"],
    "space": ["space", " "],
    "up": ["up", "arrowup"],
    "down": ["down", "arrowdown"],
    "left": ["left", "arrowleft"],
    "right": ["right", "arrowright"],
    "f1": ["f1"],
    "f2": ["f2"],
    "f3": ["f3"],
    "f4": ["f4"],
    "f5": ["f5"],
    "f6": ["f6"],
    "f7": ["f7"],
    "f8": ["f8"],
    "f9": ["f9"],
    "f10": ["f10"],
    "f11": ["f11"],
    "f12": ["f12"],
    "ctrl": ["ctrl", "control"],
    "alt": ["alt"],
    "shift": ["shift"],
    "win": ["win", "windows", "super", "command"],
}

_MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]


def normalize_key_name(key: str) -> str:
    """Normalize a key name to canonical form."""
    normalized = key.strip().lower()
    for canonical, aliases in _KEY_ALIASES.items():
        if normalized in aliases:
            return canonical
    return normalized


def normalize_hotkey(keys: str) -> List[str]:
    """Normalize a hotkey string like 'Ctrl+S' to canonical form."""
    parts = [p.strip().lower() for p in keys.split("+")]
    normalized = [normalize_key_name(p) for p in parts]
    modifiers = [p for p in normalized if p in _MODIFIER_ORDER]
    non_modifiers = [p for p in normalized if p not in _MODIFIER_ORDER]
    ordered_modifiers = sorted(modifiers, key=lambda m: _MODIFIER_ORDER.index(m))
    return ordered_modifiers + non_modifiers
