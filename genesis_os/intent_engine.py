from __future__ import annotations

import json
import re
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class IntentType(str, Enum):
    FILESYSTEM = "filesystem"
    BROWSER = "browser"
    APPLICATION = "application"
    GUI = "gui"
    SYSTEM = "system"
    CLIPBOARD = "clipboard"
    MATH = "math"
    COMPOUND = "compound"
    UNKNOWN = "unknown"


class PlanningStatus(str, Enum):
    NOT_STARTED = "not_started"
    PLANNING = "planning"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ParsedIntent:
    intent_id: str
    raw_text: str
    intent_type: IntentType
    action: str
    parameters: Dict[str, Any]
    confidence: float
    entities: List[Dict[str, Any]]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "raw_text": self.raw_text,
            "intent_type": self.intent_type.value,
            "action": self.action,
            "parameters": self.parameters,
            "confidence": self.confidence,
            "entities": self.entities,
        }


@dataclass
class PlanStep:
    step_id: str
    action: str
    parameters: Dict[str, Any]
    intent_type: IntentType
    depends_on: List[str] = field(default_factory=list)
    status: PlanningStatus = PlanningStatus.NOT_STARTED
    result: Optional[Dict[str, Any]] = None
    estimated_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "parameters": self.parameters,
            "intent_type": self.intent_type.value,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result,
        }


@dataclass
class ExecutionPlan:
    plan_id: str
    original_text: str
    steps: List[PlanStep]
    status: PlanningStatus = PlanningStatus.NOT_STARTED
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "original_text": self.original_text,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


@dataclass
class CrossAppBridge:
    bridge_id: str
    source_app: str
    target_app: str
    operation: str
    data_transform: Optional[Callable[[Any], Any]] = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bridge_id": self.bridge_id,
            "source_app": self.source_app,
            "target_app": self.target_app,
            "operation": self.operation,
            "description": self.description,
        }


class IntentEngine:
    VERSION = "1.0.0"

    INTENT_PATTERNS = {
        IntentType.FILESYSTEM: [
            r"(?:open|read|create|write|delete|copy|move|rename|search|find)\s+(?:the\s+)?(?:file|folder|directory)\s+(.+)",
            r"(?:open|read|create|write|delete|copy|move|rename)\s+(.+?\.\w+)",
            r"(?:list|show)\s+(?:the\s+)?(?:files?|folders?|contents?)\s+(?:in\s+)?(.+)",
        ],
        IntentType.BROWSER: [
            r"(?:open|go to|navigate to|visit)\s+(?:the\s+)?(?:website|page|url|site)\s+(.+)",
            r"(?:search|google|look up|find)\s+(?:for\s+)?(.+)",
            r"(?:click|tap|press)\s+(?:on\s+)?(.+)",
            r"(?:type|enter|fill)\s+(.+?)\s+(?:in|into)\s+(.+)",
            r"(?:take\s+)?screenshot",
        ],
        IntentType.APPLICATION: [
            r"(?:open|launch|start|run)\s+(.+?)(?:\s+app|\s+application)?$",
            r"(?:close|quit|exit|terminate)\s+(.+?)(?:\s+app|\s+application)?$",
        ],
        IntentType.GUI: [
            r"(?:click|tap|press)\s+(?:on\s+)?(?:the\s+)?button\s+(.+)",
            r"(?:type|enter|fill)\s+(.+?)\s+(?:in|into)\s+(?:the\s+)?(?:field|box|input|text)\s*(.*)",
            r"(?:scroll|swipe)\s+(up|down|left|right)",
        ],
        IntentType.CLIPBOARD: [
            r"(?:copy|cut|paste)\s+(.+)",
            r"(?:copy|cut|paste)\s+(?:the\s+)?(?:text|content|selection)",
        ],
        IntentType.SYSTEM: [
            r"(?:check|show|get)\s+(?:system|computer)\s+(?:status|info|information)",
            r"(?:shutdown|restart|sleep)\s+(?:the\s+)?(?:computer|system|pc)",
        ],
        IntentType.MATH: [
            r"(?:calculate|compute|evaluate|solve)\s+(.+)",
            r"what\s+is\s+(.+?)[\?]?$",
        ],
    }

    APP_ALIASES = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "browser": "chrome",
        "notepad": "notepad",
        "text editor": "notepad",
        "word": "winword",
        "microsoft word": "winword",
        "excel": "excel",
        "vs code": "code",
        "visual studio code": "code",
        "terminal": "cmd",
        "command prompt": "cmd",
        "powershell": "pwsh",
        "file explorer": "explorer",
        "explorer": "explorer",
        "calculator": "calc",
    }

    FILE_PATTERNS = [
        r"(\w+\.\w{1,5})",
        r"(C:\\.+)",
        r"(~/[^\s]+)",
        r"(\.\/[^\s]+)",
    ]

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bridges: Dict[str, CrossAppBridge] = {}
        self._plan_history: List[ExecutionPlan] = []
        self._intent_handlers: Dict[IntentType, Callable] = {}
        self._context: Dict[str, Any] = {}
        self._max_history = 200
        self._register_builtin_bridges()

    def _register_builtin_bridges(self) -> None:
        bridges = [
            CrossAppBridge(
                bridge_id="bridge-clipboard-notepad",
                source_app="clipboard",
                target_app="notepad",
                operation="paste_text",
                description="Paste clipboard content into Notepad",
            ),
            CrossAppBridge(
                bridge_id="bridge-browser-clipboard",
                source_app="chrome",
                target_app="clipboard",
                operation="extract_text_to_clipboard",
                description="Extract selected text from browser to clipboard",
            ),
            CrossAppBridge(
                bridge_id="bridge-file-notepad",
                source_app="file",
                target_app="notepad",
                operation="open_file_in_editor",
                description="Open a file in Notepad for editing",
            ),
        ]
        for bridge in bridges:
            self._bridges[bridge.bridge_id] = bridge

    def register_bridge(self, bridge: CrossAppBridge) -> None:
        with self._lock:
            self._bridges[bridge.bridge_id] = bridge

    def set_context(self, key: str, value: Any) -> None:
        with self._lock:
            self._context[key] = value

    def parse_intent(self, text: str) -> ParsedIntent:
        with self._lock:
            text = text.strip()
            intent_type, action, parameters, confidence, entities = (
                self._classify_and_extract(text)
            )

            return ParsedIntent(
                intent_id=f"intent-{int(time.time() * 1000)}",
                raw_text=text,
                intent_type=intent_type,
                action=action,
                parameters=parameters,
                confidence=confidence,
                entities=entities,
            )

    def _classify_and_extract(
        self, text: str
    ) -> Tuple[IntentType, str, Dict[str, Any], float, List[Dict[str, Any]]]:
        lower = text.lower()
        entities: List[Dict[str, Any]] = []

        best_match = (IntentType.UNKNOWN, "unknown", {}, 0.0, entities)

        for intent_type, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, lower, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    action = self._extract_action(lower, intent_type)
                    params = self._extract_parameters(intent_type, groups, text, entities)
                    confidence = 0.9 if len(groups) >= 1 else 0.7

                    if confidence > best_match[3]:
                        best_match = (intent_type, action, params, confidence, entities)

        if best_match[0] == IntentType.UNKNOWN:
            for intent_type, patterns in self.INTENT_PATTERNS.items():
                for keyword_pattern in patterns:
                    keywords = re.findall(r'\b(\w+)\b', keyword_pattern)
                    matched_keywords = [kw for kw in keywords if kw in lower.split()]
                    if len(matched_keywords) >= 2:
                        action = self._extract_action(lower, intent_type)
                        best_match = (intent_type, action, {"text": text}, 0.5, entities)
                        break
                if best_match[0] != IntentType.UNKNOWN:
                    break

        intent_type, action, params, confidence, ents = best_match
        if len(ents) == 0:
            ents = self._extract_entities(text)

        return intent_type, action, params, confidence, ents

    def _extract_action(self, text: str, intent_type: IntentType) -> str:
        action_keywords = {
            IntentType.FILESYSTEM: ["open", "read", "create", "write", "delete", "copy", "move", "rename", "search", "find", "list"],
            IntentType.BROWSER: ["open", "search", "click", "type", "navigate", "go", "visit", "screenshot"],
            IntentType.APPLICATION: ["open", "launch", "start", "run", "close", "quit", "exit"],
            IntentType.GUI: ["click", "type", "scroll", "fill", "press"],
            IntentType.CLIPBOARD: ["copy", "cut", "paste"],
            IntentType.SYSTEM: ["check", "show", "get", "shutdown", "restart"],
            IntentType.MATH: ["calculate", "compute", "evaluate", "solve"],
        }
        for kw in action_keywords.get(intent_type, []):
            if kw in text:
                return kw
        return "execute"

    def _extract_parameters(
        self,
        intent_type: IntentType,
        groups: tuple,
        text: str,
        entities: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        if intent_type == IntentType.FILESYSTEM:
            if groups:
                params["path"] = groups[0]
                entities.append({"type": "file_path", "value": groups[0]})
        elif intent_type == IntentType.BROWSER:
            if groups:
                params["query"] = groups[0]
                entities.append({"type": "search_query", "value": groups[0]})
            for pattern in self.FILE_PATTERNS:
                found = re.findall(pattern, text)
                for f in found:
                    params["url"] = f
                    entities.append({"type": "url", "value": f})
                    break
        elif intent_type == IntentType.APPLICATION:
            if groups:
                app_name = groups[0].strip().lower()
                resolved = self.APP_ALIASES.get(app_name, app_name)
                params["application"] = resolved
                entities.append({"type": "application", "value": resolved})
        elif intent_type == IntentType.MATH:
            if groups:
                params["expression"] = groups[0]
                entities.append({"type": "math_expression", "value": groups[0]})

        return params

    def _extract_entities(self, text: str) -> List[Dict[str, Any]]:
        entities = []
        for pattern in self.FILE_PATTERNS:
            found = re.findall(pattern, text)
            for f in found:
                entities.append({"type": "file_reference", "value": f})

        for app_alias, resolved in self.APP_ALIASES.items():
            if app_alias in text.lower():
                entities.append({"type": "application", "value": resolved})

        return entities

    def decompose_compound(self, text: str) -> ExecutionPlan:
        with self._lock:
            connectors = [
                "and then", "then", "after that", "next", "also",
                "and", "while", "before", "after",
            ]

            parts = [text]
            for connector in sorted(connectors, key=len, reverse=True):
                new_parts = []
                for part in parts:
                    split = re.split(rf"\b{re.escape(connector)}\b", part, flags=re.IGNORECASE)
                    new_parts.extend([s.strip() for s in split if s.strip()])
                parts = new_parts

            steps = []
            prev_step_id = None
            for i, part in enumerate(parts):
                intent = self.parse_intent(part)
                step_id = f"step-{i}"
                step = PlanStep(
                    step_id=step_id,
                    action=intent.action,
                    parameters=intent.parameters,
                    intent_type=intent.intent_type,
                    depends_on=[prev_step_id] if prev_step_id else [],
                )
                steps.append(step)
                prev_step_id = step_id

            plan = ExecutionPlan(
                plan_id=f"plan-{int(time.time() * 1000)}",
                original_text=text,
                steps=steps,
                status=PlanningStatus.READY if steps else PlanningStatus.NOT_STARTED,
            )

            self._plan_history.append(plan)
            if len(self._plan_history) > self._max_history:
                self._plan_history = self._plan_history[-self._max_history:]

            return plan

    def find_bridges(
        self, source_app: str, target_app: str
    ) -> List[CrossAppBridge]:
        with self._lock:
            return [
                b for b in self._bridges.values()
                if b.source_app.lower() == source_app.lower()
                and b.target_app.lower() == target_app.lower()
            ]

    def suggest_bridges(self, intent: ParsedIntent) -> List[CrossAppBridge]:
        with self._lock:
            suggestions = []
            if intent.intent_type == IntentType.APPLICATION:
                app = intent.parameters.get("application", "")
                for bridge in self._bridges.values():
                    if bridge.source_app.lower() == app.lower():
                        suggestions.append(bridge)
            elif intent.intent_type == IntentType.BROWSER:
                for bridge in self._bridges.values():
                    if bridge.source_app.lower() == "chrome":
                        suggestions.append(bridge)
            return suggestions

    def update_plan_step(
        self, plan_id: str, step_id: str, status: PlanningStatus, result: Optional[Dict[str, Any]] = None
    ) -> bool:
        with self._lock:
            for plan in self._plan_history:
                if plan.plan_id == plan_id:
                    for step in plan.steps:
                        if step.step_id == step_id:
                            step.status = status
                            step.result = result
                            if all(s.status == PlanningStatus.COMPLETED for s in plan.steps):
                                plan.status = PlanningStatus.COMPLETED
                                plan.completed_at = time.time()
                            elif any(s.status == PlanningStatus.FAILED for s in plan.steps):
                                plan.status = PlanningStatus.FAILED
                            return True
            return False

    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        with self._lock:
            for plan in self._plan_history:
                if plan.plan_id == plan_id:
                    return plan
            return None

    def get_intent_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "total_plans": len(self._plan_history),
                "total_bridges": len(self._bridges),
                "registered_bridges": [b.to_dict() for b in self._bridges.values()],
                "context_keys": list(self._context.keys()),
            }
