"""Deprecated dormant duplicate of the Phase 2 tool boundary.

``SemanticCapabilityAdapter`` was an early Genesis-native sketch. It
builds OpenAI-shaped definitions, but its handlers call ``OSManager``
directly and therefore bypass ``ActionPlan``, ``ActionExecutor``, the
approval gate, and the Phase 1 Evidence contract. The production Phase 2
implementation is ``AgentFrameworkAdapter``, which routes every tool call
through the canonical executor and is now owned by ``GenesisOS``.

This module remains import-compatible for historical callers, but it is
not wired into production and must not be used as a second execution
boundary. It is retained only as a documented dead-code reference until
the later cleanup phase removes it.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from .capability_registry import CapabilityRegistry
from .security_model import assess_operation_risk


class SemanticCapabilityFunction:
    """A single AI-callable capability function.

    Wraps a capability with semantic metadata so LLMs can
    discover and invoke it through structured tool calling.
    """

    def __init__(
        self,
        function_id: str,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        capability_id: str,
        handler: Callable[..., Any],
        risk_level: str = "low",
        requires_confirmation: bool = False,
    ):
        self.function_id = function_id
        self.name = name
        self.description = description
        self.parameters = parameters
        self.capability_id = capability_id
        self.handler = handler
        self.risk_level = risk_level
        self.requires_confirmation = requires_confirmation

    def to_tool_definition(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible tool/function definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function_id": self.function_id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "capability_id": self.capability_id,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
        }
class SemanticCapabilityAdapter:
    """Deprecated dormant sketch; use ``AgentFrameworkAdapter``.

    The class remains import-compatible for historical code, but its
    handlers bypass the canonical executor boundary. Production Phase 2
    routing is owned by ``AgentFrameworkAdapter``.
    """


    def __init__(self, os_manager: Any = None):
        self._os_manager = os_manager
        self._registry: Optional[CapabilityRegistry] = None
        self._functions: Dict[str, SemanticCapabilityFunction] = {}
        self._build_functions()

    def _get_registry(self) -> CapabilityRegistry:
        if self._registry is None:
            self._registry = CapabilityRegistry()
        return self._registry

    def _build_functions(self) -> None:
        """Build semantic function definitions for all capabilities."""
        # Filesystem operations
        self._register(
            "file_open",
            "open_file",
            "Open a file or folder on the system. Returns the result of the open operation.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or folder path to open"},
                },
                "required": ["path"],
            },
            "file.open",
            self._handle_file_open,
        )
        self._register(
            "file_read",
            "read_file",
            "Read the contents of a file. Returns the file content as text.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
            "file.read",
            self._handle_file_read,
        )
        self._register(
            "file_create",
            "create_file",
            "Create a new file with optional content.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to create"},
                    "content": {"type": "string", "description": "File content", "default": ""},
                },
                "required": ["path"],
            },
            "file.create",
            self._handle_file_create,
            risk_level="medium",
        )
        self._register(
            "file_copy",
            "copy_file",
            "Copy a file from source to destination.",
            {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source file path"},
                    "destination": {"type": "string", "description": "Destination path"},
                },
                "required": ["source", "destination"],
            },
            "file.copy",
            self._handle_file_copy,
            risk_level="medium",
            requires_confirmation=True,
        )
        self._register(
            "file_delete",
            "delete_file",
            "Delete a file. This is destructive and requires confirmation.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                },
                "required": ["path"],
            },
            "file.delete",
            self._handle_file_delete,
            risk_level="high",
            requires_confirmation=True,
        )
        self._register(
            "file_search",
            "search_files",
            "Search for files matching a pattern.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to search in"},
                    "query": {"type": "string", "description": "Search query or pattern"},
                },
                "required": ["path", "query"],
            },
            "file.search",
            self._handle_file_search,
        )
        self._register(
            "file_inspect",
            "inspect_file",
            "Inspect file metadata (size, type, dates).",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to inspect"},
                },
                "required": ["path"],
            },
            "file.inspect",
            self._handle_file_inspect,
        )

        # Folder operations
        self._register(
            "folder_create",
            "create_folder",
            "Create a new folder.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder path to create"},
                },
                "required": ["path"],
            },
            "folder.create",
            self._handle_folder_create,
            risk_level="medium",
        )
        self._register(
            "folder_list",
            "list_folder",
            "List contents of a folder.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder path to list"},
                },
                "required": ["path"],
            },
            "folder.list",
            self._handle_folder_list,
        )

        # Browser operations
        self._register(
            "browser_navigate",
            "navigate_browser",
            "Navigate the browser to a URL.",
            {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                },
                "required": ["url"],
            },
            "browser.open_url",
            self._handle_browser_navigate,
        )
        self._register(
            "browser_search",
            "web_search",
            "Search the web using a search engine.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "engine": {"type": "string", "description": "Search engine", "default": "google"},
                },
                "required": ["query"],
            },
            "browser.search",
            self._handle_browser_search,
        )
        self._register(
            "browser_click",
            "click_element",
            "Click an element on a web page by CSS selector.",
            {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector"},
                },
                "required": ["selector"],
            },
            "browser.click",
            self._handle_browser_click,
            risk_level="medium",
        )
        self._register(
            "browser_type",
            "type_in_browser",
            "Type text into a web page element.",
            {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector"},
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["selector", "text"],
            },
            "browser.type",
            self._handle_browser_type,
            risk_level="medium",
        )
        self._register(
            "browser_screenshot",
            "take_screenshot",
            "Take a screenshot of the current browser page.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Save path for screenshot"},
                },
            },
            "browser.screenshot",
            self._handle_browser_screenshot,
        )

        # Application operations
        self._register(
            "app_open",
            "open_application",
            "Open an application by name.",
            {
                "type": "object",
                "properties": {
                    "application": {"type": "string", "description": "Application name"},
                },
                "required": ["application"],
            },
            "application.open",
            self._handle_app_open,
            risk_level="medium",
        )
        self._register(
            "app_close",
            "close_application",
            "Close an application by name.",
            {
                "type": "object",
                "properties": {
                    "application": {"type": "string", "description": "Application name"},
                },
                "required": ["application"],
            },
            "application.close",
            self._handle_app_close,
            risk_level="medium",
            requires_confirmation=True,
        )
        self._register(
            "app_inspect",
            "inspect_application",
            "Inspect the state of a running application.",
            {
                "type": "object",
                "properties": {
                    "application": {"type": "string", "description": "Application name"},
                },
                "required": ["application"],
            },
            "application.inspect",
            self._handle_app_inspect,
        )

        # GUI operations
        self._register(
            "gui_click",
            "gui_click",
            "Click at screen coordinates.",
            {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                },
                "required": ["x", "y"],
            },
            "gui.click",
            self._handle_gui_click,
            risk_level="medium",
        )
        self._register(
            "gui_type",
            "gui_type_text",
            "Type text at the current cursor position.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
            },
            "gui.type_text",
            self._handle_gui_type,
            risk_level="medium",
        )

        # System operations
        self._register(
            "system_status",
            "system_status",
            "Get system status (CPU, memory, battery).",
            {"type": "object", "properties": {}},
            "system.status",
            self._handle_system_status,
        )
        self._register(
            "clipboard_copy",
            "clipboard_copy",
            "Copy text to the clipboard.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to copy"},
                },
                "required": ["text"],
            },
            "clipboard.copy",
            self._handle_clipboard_copy,
        )
        self._register(
            "clipboard_paste",
            "clipboard_paste",
            "Read text from the clipboard.",
            {"type": "object", "properties": {}},
            "clipboard.paste",
            self._handle_clipboard_paste,
        )

        # Math operations
        self._register(
            "math_evaluate",
            "calculate",
            "Evaluate a mathematical expression.",
            {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"},
                },
                "required": ["expression"],
            },
            "math.evaluate",
            self._handle_math_evaluate,
        )

        # Notes
        self._register(
            "note_create",
            "create_note",
            "Create a new note.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Note content"},
                },
                "required": ["text"],
            },
            "notes.create",
            self._handle_note_create,
        )

    def _register(
        self,
        function_id: str,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        capability_id: str,
        handler: Callable[..., Any],
        risk_level: str = "low",
        requires_confirmation: bool = False,
    ) -> None:
        self._functions[function_id] = SemanticCapabilityFunction(
            function_id=function_id,
            name=name,
            description=description,
            parameters=parameters,
            capability_id=capability_id,
            handler=handler,
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
        )

    # =========================================================
    # PUBLIC API
    # =========================================================

    def list_functions(self) -> List[Dict[str, Any]]:
        """List all available semantic functions."""
        return [f.to_dict() for f in self._functions.values()]

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible tool definitions for all functions."""
        return [f.to_tool_definition() for f in self._functions.values()]

    def get_function(self, name: str) -> Optional[SemanticCapabilityFunction]:
        """Get a specific function by name."""
        return self._functions.get(name)

    def invoke(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke a semantic function by name with arguments.

        Routes through the SAME authorization authority the executor uses.

        CHOICE (2026-10-15, Item 3B-2) -- why the gate, not the executor
        ------------------------------------------------------
        The directive allowed either routing through
        ``ActionExecutor.execute(plan)`` or requiring the shared
        ``_operation_requires_authorization`` + a valid grant before the
        handler reaches the manager. This module chose the SECOND.

        Reason: this adapter's 48 registrations are not all canonical
        executor capabilities -- ``_build_action_plan`` raises
        ``ValueError`` for any id it does not know -- so routing every
        invoke through the executor would break the unknown ones. The
        gate is one insertion point, covers all 24 handlers, and calls
        the very same ``_operation_requires_authorization`` the executor
        gate calls, so there is still exactly ONE authority for "is this
        Tier 1". It is defence at the boundary, not a parallel system.

        Before this, the only check was a CONTEXT-FREE
        ``assess_operation_risk(func.capability_id, arguments)``. That is
        a risk heuristic, not the authorization gate, and it let a Tier 1
        capability reach ``os_manager.delete_file`` with no grant at all.
        """
        func = self._functions.get(function_name)
        if func is None:
            return {
                "success": False,
                "error": f"Unknown function: {function_name}",
                "available_functions": list(self._functions.keys()),
            }

        # ONE AUTHORITY: the shared gate. Tier 1 (irreversible or
        # outward-facing) requires a real AuthorizationGrant, exactly as
        # it would through the executor. Fails closed.
        authorization = self._require_authorization(func, arguments)
        if authorization is not None:
            return authorization

        # A VALID GRANT IS THE AUTHORITY. When one is present the
        # context-free risk heuristic below is advisory only: it exists to
        # ASK for approval, and a human already gave one through the
        # token that minted this grant. Blocking a properly authorised
        # call on a heuristic would make the grant meaningless.
        has_grant = self._has_valid_grant(func, arguments)

        # Security check (heuristic; not the authority)
        risk = assess_operation_risk(func.capability_id, arguments)
        if risk.requires_confirmation and not has_grant:
            return {
                "success": False,
                "requires_confirmation": True,
                "risk_level": risk.risk_level.value,
                "reason": risk.reason,
                "function": function_name,
                "arguments": arguments,
            }

        # Execute
        try:
            result = func.handler(arguments)
            if isinstance(result, dict):
                result.setdefault("_function", function_name)
                result.setdefault("_capability", func.capability_id)
            return result
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "function": function_name,
            }

    def _operation_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """The arguments an authorization hash binds to.

        Authority is not an argument, so ``authorization`` is excluded --
        exactly as the executor keeps the grant off ``parameters``.
        """
        return {
            key: value
            for key, value in dict(arguments).items()
            if key != "authorization"
        }

    def _has_valid_grant(
        self,
        func: "SemanticCapabilityFunction",
        arguments: Dict[str, Any],
    ) -> bool:
        """Whether a valid AuthorizationGrant accompanies this call."""
        from .authorization_grant import grant_is_valid_for

        grant = arguments.get("authorization")
        if grant is None:
            return False
        try:
            return bool(grant_is_valid_for(
                grant,
                operation=func.capability_id,
                arguments=self._operation_arguments(arguments),
            ))
        except Exception:
            return False

    def _require_authorization(
        self,
        func: "SemanticCapabilityFunction",
        arguments: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Refuse a Tier 1 capability that has no valid grant.

        Returns ``None`` when the call may proceed, or a
        ``confirmation_required`` envelope when it may not.

        The grant is read from ``arguments["authorization"]`` (the
        trusted channel the adapter attaches) and validated with the
        shared ``grant_is_valid_for``, which re-derives the canonical
        argument hash. A caller cannot satisfy this by putting anything
        in model-controlled JSON, because a grant can only be minted
        from a consumed, human-approved record.

        The grant itself is EXCLUDED from the hashed arguments: it is
        authority, not an argument, so it must not change the hash the
        grant was bound to. This mirrors the executor, where the grant
        travels on ``plan.authorization`` rather than inside
        ``parameters``.
        """
        from .action_executor import _operation_requires_authorization

        operation_arguments = self._operation_arguments(arguments)

        try:
            gated = _operation_requires_authorization(
                func.capability_id,
                func.capability_id,
                dict(operation_arguments),
            )
        except Exception:
            # Cannot classify -> treat as gated. Deny-by-default.
            gated = True

        if not gated:
            return None

        if self._has_valid_grant(func, arguments):
            return None

        return {
            "success": False,
            "status": "confirmation_required",
            "requires_confirmation": True,
            "confirmation_required": True,
            "reason": (
                f"{func.capability_id} is irreversible or outward-facing "
                f"and requires a human-approval AuthorizationGrant. "
                f"Attach a valid `authorization` grant to the arguments; "
                f"`confirmed` is not an authority."
            ),
            "function": func.function_id,
            "capability": func.capability_id,
            "executed": False,
            "verified": False,
        }

    # =========================================================
    # HANDLERS
    # =========================================================

    def _handle_file_open(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.open_file(args["path"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_file_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.read_file(args["path"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_file_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.create_file(args["path"], args.get("content", ""))
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_file_copy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.copy_file(args["source"], args["destination"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_file_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.delete_file(args["path"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_file_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.search_file(args["path"], args["query"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_file_inspect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.inspect_file(args["path"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_folder_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.create_folder(args["path"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_folder_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.list_folder(args["path"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_browser_navigate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.open_url(args["url"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_browser_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.web_search(args["query"], args.get("engine", "google"))
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_browser_click(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.browser_click(args["selector"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_browser_type(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.browser_type(args["selector"], args["text"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_browser_screenshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.browser_screenshot(args.get("path"))
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_app_open(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.open_application(args["application"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_app_close(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.close_application(args["application"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_app_inspect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.inspect_application(args["application"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_gui_click(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.gui_action("click", x=args["x"], y=args["y"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_gui_type(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.gui_action("type_text", text=args["text"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_system_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.system_status()
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_clipboard_copy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.clipboard_copy(args["text"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_clipboard_paste(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.clipboard_paste()
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_math_evaluate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.calculate(args["expression"])
        return {"success": False, "error": "OS manager not initialized"}

    def _handle_note_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._os_manager:
            return self._os_manager.create_note(args["text"])
        return {"success": False, "error": "OS manager not initialized"}
