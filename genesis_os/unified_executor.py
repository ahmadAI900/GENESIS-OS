"""
Genesis OS — Level 3 Mixed Intelligence + OS Workflow Integration.

Automatic agent selection and unified execution for mixed requests:

    "Research three laptops, compare in Excel, save to Shopping folder"
          ↓
    Research Agent (intelligence)
          ↓
    Data Agent (structure/compare)
          ↓
    Level 3: Create/open Excel, write data, save, verify
          ↓
    Unified result

This module connects the WorkflowDecisionEngine, Level 2 agents,
and Level 3 workflow engine into a single coherent pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.agent_registry import AgentRegistry
from agents.workflow_decision import WorkflowDecisionEngine
from agents.base_agent import BaseAgent
from genesis_os.workflow_models import WorkflowPlan, WorkflowStep
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.action_plan import ActionPlan
from genesis_os.session_state import SessionState
from genesis_os.context_resolver import ContextResolver
from genesis_os.os_manager import OSManager


@dataclass
class AgentTask:
    """A task assigned to a Level 2 agent."""
    agent_name: str
    task: str
    context: Dict[str, Any] = field(default_factory=dict)
    depends_on: Tuple[str, ...] = ()
    step_id: str = ""


@dataclass
class OSWorkflowStep:
    """An OS workflow step derived from agent results."""
    step_id: str
    action_plan: ActionPlan
    depends_on: Tuple[str, ...] = ()
    agent_source: Optional[str] = None  # Which agent produced the data for this step


@dataclass
class MixedWorkflowPlan:
    """Complete plan combining Level 2 agents and Level 3 OS steps."""
    objective: str
    agent_tasks: List[AgentTask]
    os_steps: List[OSWorkflowStep]
    workflow_id: str = ""


@dataclass
class MixedWorkflowResult:
    """Result of executing a mixed workflow."""
    success: bool
    objective: str
    agent_results: List[Dict[str, Any]]
    os_results: List[Dict[str, Any]]
    final_verified: bool
    message: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentCapabilityMapper:
    """
    Maps natural language to Level 2 agent capabilities.
    
    Used for automatic agent selection without user specifying agent names.
    """

    AGENT_CAPABILITIES = {
        "Research Agent": {
            "keywords": ["research", "investigate", "look up", "find information", "search for", "explore"],
            "triggers": ["research", "investigate", "find out", "look into", "search"],
            "outputs": ["structured findings", "citations", "summaries"],
            "priority": 10,
        },
        "Coding Agent": {
            "keywords": ["code", "program", "script", "function", "debug", "fix bug", "implement"],
            "triggers": ["write code", "create script", "debug", "fix", "implement", "program"],
            "outputs": ["code files", "patches", "explanations"],
            "priority": 50,
        },
        "Study Agent": {
            "keywords": ["study", "learn", "quiz", "flashcard", "memorize", "practice", "exam"],
            "triggers": ["study", "learn", "quiz me", "test me", "practice", "memorize"],
            "outputs": ["study plans", "quizzes", "flashcards", "explanations"],
            "priority": 90,
        },
        "Internet Agent": {
            "keywords": ["search", "google", "web search", "online", "website", "browse"],
            "triggers": ["search the web", "google", "find online", "browse"],
            "outputs": ["search results", "URLs", "snippets"],
            "priority": 15,
        },
        "Document Agent": {
            "keywords": ["document", "pdf", "word", "docx", "summarize", "extract", "read document"],
            "triggers": ["summarize", "read pdf", "extract from", "document", "pdf"],
            "outputs": ["summaries", "extracted text", "document analyses"],
            "priority": 20,
        },
        "Design Agent": {
            "keywords": ["design", "ui", "ux", "wireframe", "mockup", "palette", "color"],
            "triggers": ["design", "create design", "mockup", "wireframe", "color palette"],
            "outputs": ["design specs", "SVGs", "palettes", "mockups"],
            "priority": 60,
        },
        "Business Agent": {
            "keywords": ["business", "strategy", "market", "financial", "plan", "roi", "startup"],
            "triggers": ["business plan", "market research", "financial", "strategy", "startup"],
            "outputs": ["business plans", "analyses", "financial models"],
            "priority": 70,
        },
        "Data Agent": {
            "keywords": ["data", "analyze", "csv", "excel", "statistics", "chart", "graph", "plot"],
            "triggers": ["analyze data", "csv", "excel", "statistics", "chart", "visualize"],
            "outputs": ["analyses", "charts", "transformed data", "insights"],
            "priority": 30,
        },
        "Planning Agent": {
            "keywords": ["plan", "schedule", "timeline", "roadmap", "project plan", "organize"],
            "triggers": ["plan", "schedule", "roadmap", "timeline", "organize project"],
            "outputs": ["project plans", "timelines", "task breakdowns"],
            "priority": 40,
        },
        "Security Agent": {
            "keywords": ["security", "vulnerability", "audit", "penetration", "secure", "threat"],
            "triggers": ["security audit", "vulnerability", "penetration test", "secure"],
            "outputs": ["security reports", "vulnerability lists", "recommendations"],
            "priority": 80,
        },
    }

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def identify_required_agents(self, text: str) -> List[str]:
        """Identify which agents are needed for the request."""
        text_lower = text.lower()
        required = []

        for agent_name, caps in self.AGENT_CAPABILITIES.items():
            if not self.registry.get_agent(agent_name):
                continue

            # Check triggers (higher priority)
            for trigger in caps.get("triggers", []):
                if trigger in text_lower:
                    required.append((agent_name, caps.get("priority", 99)))
                    break

            # Check keywords if no trigger matched
            if not any(r[0] == agent_name for r in required):
                for keyword in caps.get("keywords", []):
                    if keyword in text_lower:
                        required.append((agent_name, caps.get("priority", 99)))
                        break

        # Sort by priority
        required.sort(key=lambda x: x[1])
        return [agent for agent, _ in required]

    def get_agent_output_type(self, agent_name: str) -> str:
        """Get the expected output type for an agent."""
        caps = self.AGENT_CAPABILITIES.get(agent_name, {})
        return caps.get("outputs", ["result"])[0]


class MixedWorkflowPlanner:
    """
    Plans mixed workflows combining Level 2 agents and Level 3 OS operations.
    
    Takes a user objective and produces a MixedWorkflowPlan that specifies:
    - Which Level 2 agents to run and in what order
    - What OS operations to perform based on agent outputs
    - Dependencies between agents and OS steps
    """

    def __init__(
        self,
        agent_mapper: AgentCapabilityMapper,
        decision_engine: WorkflowDecisionEngine,
        context_resolver: ContextResolver,
    ):
        self.agent_mapper = agent_mapper
        self.decision_engine = decision_engine
        self.context_resolver = context_resolver

    def plan(self, objective: str) -> MixedWorkflowPlan:
        """Create a mixed workflow plan from a natural language objective."""
        import re

        # 1. Identify required agents
        mapped_agents = self.agent_mapper.identify_required_agents(objective)
        router_agents: List[str] = []

        # 2. Detect OS intents by splitting the request on
        # coordinating conjunctions. A compound request like
        # "Research laptops and open Chrome" collapses to L1
        # at the full-string level (because "Research laptops"
        # is an L2 Research Agent task, not an OS op), so the
        # OS clause is masked. Splitting on "and" / "then" /
        # "," lets us discover the OS clause and add it to
        # the mixed plan alongside the agent tasks.
        os_clauses: List[Dict[str, Any]] = []
        has_os_intent = False

        try:
            parts = self._split_compound(objective)
        except Exception:
            parts = [objective]

        for part in parts:
            part_stripped = part.strip()
            if not part_stripped:
                continue
            try:
                part_decision = self.decision_engine.decide(part_stripped)
            except Exception:
                continue
            if self._is_os_intent(part_decision):
                os_clauses.append(part_decision)
                has_os_intent = True
            elif (
                isinstance(part_decision, dict)
                and part_decision.get("level") == 2
            ):
                names = list(part_decision.get("agents") or [])
                agent_name = part_decision.get("agent")
                if agent_name:
                    names.insert(0, agent_name)
                for name in names:
                    if name and name not in router_agents:
                        router_agents.append(name)

        required_agents = router_agents or mapped_agents

        # Pick the first OS clause for the initial step
        # construction. The refinements layer may add more
        # based on agent outputs.
        os_decision = os_clauses[0] if os_clauses else self.decision_engine.decide(objective)

        # 3. Build agent tasks
        agent_tasks = self._build_agent_tasks(objective, required_agents)

        # 4. Build OS steps (will be refined after agent execution)
        os_steps: List[OSWorkflowStep] = []
        if has_os_intent:
            os_steps = self._build_initial_os_steps(objective, os_decision, agent_tasks, os_clauses)

        return MixedWorkflowPlan(
            objective=objective,
            agent_tasks=agent_tasks,
            os_steps=os_steps,
            workflow_id=f"mixed-{hash(objective)}",
        )

    @staticmethod
    def _split_compound(text: str) -> List[str]:
        """Split a compound request on coordinating conjunctions.

        This is the L2/L3 planning seam. The full request may
        collapse to L1 (e.g. "Research laptops and open Chrome"
        routes to L1 conversation because the L2 Research Agent
        keyword dominates the routing). Splitting surfaces the
        per-clause L3 OS intent (e.g. "open Chrome" -> L3
        application.open).
        """
        import re as _re
        return [p for p in _re.split(r'\s+(?:and|then|,)\s+', text) if p.strip()]

    @staticmethod
    def _is_os_intent(decision: Dict[str, Any]) -> bool:
        """True when the decision routed to Level 3 OS."""
        if not isinstance(decision, dict):
            return False
        if decision.get("level") != 3:
            return False
        intent = decision.get("intent") or ""
        if not intent:
            return False
        os_prefixes = (
            "application.", "folder.", "file.", "browser.",
            "document.", "spreadsheet.", "data.",
            "system.", "network.", "process.", "media.",
            "volume.", "display.", "hardware.", "clipboard.",
            "screen.", "workstation.", "window.", "web.weather",
            "time.", "math.", "notes.", "package.", "cleanup.",
            "gui.",
        )
        return any(intent.startswith(p) for p in os_prefixes)

    def _build_agent_tasks(
        self,
        objective: str,
        required_agents: List[str],
    ) -> List[AgentTask]:
        """Build ordered agent tasks with dependencies."""
        tasks = []
        # Order agents by typical pipeline: Research -> Data/Document -> Planning -> OS
        agent_order = [
            "Research Agent",
            "Internet Agent",
            "Document Agent",
            "Data Agent",
            "Security Agent",
            "Planning Agent",
            "Coding Agent",
            "Design Agent",
            "Business Agent",
            "Study Agent",
        ]

        for i, agent_name in enumerate(agent_order):
            if agent_name in required_agents:
                depends_on = tuple(f"agent-{j}" for j in range(i) if agent_order[j] in required_agents)
                tasks.append(AgentTask(
                    agent_name=agent_name,
                    task=objective,
                    step_id=f"agent-{i}",
                    depends_on=depends_on,
                ))

        return tasks

    def _build_initial_os_steps(
        self,
        objective: str,
        os_decision: Dict[str, Any],
        agent_tasks: List[AgentTask],
        os_clauses: Optional[List[Dict[str, Any]]] = None,
    ) -> List[OSWorkflowStep]:
        """Build initial OS steps based on detected intent(s).

        When ``os_clauses`` is provided (multi-clause mixed
        request), every OS clause becomes one OSWorkflowStep
        in execution order. The first clause depends on the
        last agent; subsequent clauses depend on the previous
        OS step so the workflow engine preserves the order the
        user asked for ("open Chrome and search for python
        tutorials" runs both steps in sequence, not in
        parallel).
        """
        steps: List[OSWorkflowStep] = []
        step_counter = 1

        clauses: List[Dict[str, Any]] = list(os_clauses) if os_clauses else [os_decision]

        last_agent = agent_tasks[-1].step_id if agent_tasks else None
        previous_os_step_id: Optional[str] = None

        for clause in clauses:
            intent = clause.get("intent", "")
            target = clause.get("target")
            application = clause.get("application")
            parameters = dict(clause.get("parameters") or {})
            confidence = float(clause.get("confidence") or 0.90)

            step = self._make_os_step(
                intent=intent,
                target=target,
                application=application,
                parameters=parameters,
                confidence=confidence,
                step_id=f"os-{step_counter}",
            )
            if step is None:
                continue

            depends_on: List[str] = []
            if last_agent:
                depends_on.append(last_agent)
            if previous_os_step_id:
                depends_on.append(previous_os_step_id)
            step.depends_on = tuple(depends_on)

            steps.append(step)
            previous_os_step_id = step.step_id
            step_counter += 1

        return steps

    @staticmethod
    def _make_os_step(
        *,
        intent: str,
        target: Optional[str],
        application: Optional[str],
        parameters: Dict[str, Any],
        confidence: float,
        step_id: str,
    ) -> Optional[OSWorkflowStep]:
        """Build a single OSWorkflowStep for one L3 clause.

        Returns ``None`` when the clause cannot be translated
        into an ``ActionPlan`` (missing target or unsupported
        intent for the mixed planner). The caller will skip
        the clause; the runtime engine has its own full
        single-step planner for every supported intent.
        """
        if not intent:
            return None
        # GUI typing/pasting can carry target=None when the
        # user did not name a window ("type Hello") — the
        # executor types into whatever window currently has
        # focus. Skip the "missing target" gate for these
        # intents, since they ARE dispatchable as-is.
        if (
            not target
            and not application
            and intent not in ("gui.type_text", "gui.paste_text")
        ):
            return None

        # Map the planner's intent vocabulary onto the
        # ``ActionPlan.operation`` vocabulary the executor
        # accepts. This is intentionally a small allow-list:
        # the mixed planner only schedules the intents whose
        # agent-derived data the runtime can carry forward
        # into the L3 dispatch.
        if intent == "application.open":
            operation = "application.open"
            op_target = target or application
            op_application = target or application
            op_conf = max(confidence, 0.95)
        elif intent == "folder.open":
            operation = "folder.open"
            op_target = target
            op_application = None
            op_conf = max(confidence, 0.95)
        elif intent == "folder.create":
            operation = "folder.create"
            op_target = target
            op_application = None
            op_conf = max(confidence, 0.97)
        elif intent == "file.create":
            operation = "file.create"
            op_target = target
            op_application = None
            op_conf = max(confidence, 0.90)
        elif intent in ("gui.type_text", "gui.paste_text"):
            operation = intent
            op_target = target
            op_application = application
            op_conf = max(confidence, 0.95)
        else:
            # Any other L3 OS intent: schedule it verbatim
            # so the executor's dispatch layer handles it.
            operation = intent
            op_target = target
            op_application = application
            op_conf = max(confidence, 0.90)

        # Carry forward every parameter the decision engine
        # set (query, engine, folder, etc.) and add the
        # unified-executor markers the runtime expects.
        merged_parameters: Dict[str, Any] = dict(parameters or {})

        # Mixed executor's OS steps derive from a natural-
        # language request that the user already confirmed by
        # sending it. Pre-set ``confirmed=True`` for non
        # destructive operations so the executor's
        # confirmation gate (which protects interactive users
        # from accidental destructive mutations) does not
        # block the L3 dispatch when the unified executor is
        # carrying the L2 agent's output forward into the
        # filesystem. Truly destructive ops (file.delete,
        # folder.delete) keep the default gate.
        destructive = {
            "file.delete", "folder.delete", "folder.move",
            "folder.rename", "file.move", "file.rename",
            "cleanup.empty_recycle_bin",
        }
        if operation not in destructive:
            merged_parameters.setdefault("confirmed", True)

        return OSWorkflowStep(
            step_id=step_id,
            action_plan=ActionPlan(
                operation=operation,
                target=op_target,
                application=op_application,
                confidence=op_conf,
                parameters=merged_parameters,
            ),
        )

    def refine_os_steps_from_agent_results(
        self,
        plan: MixedWorkflowPlan,
        agent_results: List[Dict[str, Any]],
    ) -> List[OSWorkflowStep]:
        """
        Refine OS steps based on actual agent outputs.
        
        This is called after agents complete to build precise OS operations
        from the structured data agents produced.
        """
        refined_steps = []

        # Collect all agent outputs
        all_data = {}
        agent_result_by_name = {}
        for result in agent_results:
            if result.get("success"):
                agent = result.get("agent", "unknown")
                agent_result_by_name[agent] = result
                response = result.get("response")
                if response is None:
                    for key in ("findings", "analysis", "code", "content", "text", "result"):
                        if result.get(key) not in (None, ""):
                            response = result[key]
                            break
                if response not in (None, ""):
                    all_data[agent] = response

        step_counter = 100  # High number to avoid collisions with pre-existing os_steps
        last_agent_step = plan.agent_tasks[-1].step_id if plan.agent_tasks else None

        # --- Data Agent: extract file paths, CSV/Excel refs, and recommendations ---
        if "Data Agent" in all_data:
            data_response = all_data["Data Agent"]
            data_text = data_response if isinstance(data_response, str) else str(data_response)

            # Extract file paths (CSV, Excel, etc.)
            file_paths = re.findall(
                r'(?:[\w\\/:.~-]+[/\\])[\w.-]+\.(?:csv|xlsx?|tsv|parquet|json)',
                data_text,
                re.IGNORECASE,
            )
            # Also match bare filenames like "report.csv"
            bare_files = re.findall(
                r'\b([\w.-]+\.(?:csv|xlsx?|tsv|parquet|json))\b',
                data_text,
                re.IGNORECASE,
            )
            all_data_paths = list(dict.fromkeys(file_paths + bare_files))  # dedupe, preserve order

            for fpath in all_data_paths:
                refined_steps.append(OSWorkflowStep(
                    step_id=f"agent-os-{step_counter}",
                    action_plan=ActionPlan(
                        operation="file.open",
                        target=fpath,
                        confidence=0.88,
                        reason=f"Data Agent referenced file: {fpath}",
                        source="UnifiedExecutor.refine_os_steps_from_agent_results",
                        parameters={"agent": "Data Agent"},
                    ),
                    depends_on=(last_agent_step,) if last_agent_step else (),
                    agent_source="Data Agent",
                ))
                step_counter += 1

            # Detect recommendation to create spreadsheet summaries
            create_spreadsheet_patterns = [
                r'(?:create|generate|make|produce)\s+(?:an?\s+)?(?:excel|spreadsheet|summary\s+table)',
                r'(?:export|save|write)\s+(?:to|as)\s+(?:excel|xlsx?|spreadsheet)',
            ]
            for pattern in create_spreadsheet_patterns:
                if re.search(pattern, data_text, re.IGNORECASE):
                    # Determine target filename from extracted paths or use default
                    target_name = "summary.xlsx"
                    for p in all_data_paths:
                        if p.lower().endswith(('.csv', '.tsv', '.parquet')):
                            target_name = p.rsplit('.', 1)[0] + ".xlsx"
                            break
                    refined_steps.append(OSWorkflowStep(
                        step_id=f"agent-os-{step_counter}",
                        action_plan=ActionPlan(
                            operation="file.create",
                            target=target_name,
                            application="Excel",
                            confidence=0.85,
                            reason="Data Agent recommended creating spreadsheet summary",
                            source="UnifiedExecutor.refine_os_steps_from_agent_results",
                            parameters={
                                "agent": "Data Agent",
                                "source_files": all_data_paths[:5],
                            },
                        ),
                        depends_on=(last_agent_step,) if last_agent_step else (),
                        agent_source="Data Agent",
                    ))
                    step_counter += 1
                    break  # Only add once

            # Detect sort/analysis recommendations
            if re.search(r'\b(?:sort|rank|top\s+\d+|highest|lowest|average|mean|median)\b', data_text, re.IGNORECASE):
                for fpath in all_data_paths[:2]:
                    refined_steps.append(OSWorkflowStep(
                        step_id=f"agent-os-{step_counter}",
                        action_plan=ActionPlan(
                            operation="spreadsheet.sort",
                            target=fpath,
                            confidence=0.82,
                            reason="Data Agent suggested sort/analysis operation",
                            source="UnifiedExecutor.refine_os_steps_from_agent_results",
                            parameters={"agent": "Data Agent"},
                        ),
                        depends_on=(last_agent_step,) if last_agent_step else (),
                        agent_source="Data Agent",
                    ))
                    step_counter += 1

        # --- Coding Agent: extract code blocks and file paths, write to disk ---
        if "Coding Agent" in all_data:
            code_response = all_data["Coding Agent"]
            code_text = code_response if isinstance(code_response, str) else str(code_response)

            # Extract file paths from fenced code blocks: ```language path/to/file.py
            fenced_files = re.findall(
                r'```(?:\w+)?\s+([^\s`]+\.\w+)\s*\n',
                code_text,
            )
            # Extract paths from "create/write/save file" patterns
            action_files = re.findall(
                r'(?:create|write|save|generate|output)\s+(?:file\s+)?[`"\']*([~]?[/\\]?[\w.-]+\.\w+)[`"\']*',
                code_text,
                re.IGNORECASE,
            )
            # Extract paths from "to path/to/file" patterns
            target_files = re.findall(
                r'\b(?:to|at|in)\s+([~]?[/\\]?[\w.-]+\.(?:py|js|ts|jsx|tsx|java|c|cpp|h|go|rs|rb|sh|bat|ps1|yaml|yml|json|toml|css|html|sql))\b',
                code_text,
            )

            code_files = list(dict.fromkeys(fenced_files + action_files + target_files))
            structured_result = agent_result_by_name.get("Coding Agent", {})
            structured_code = (
                structured_result.get("code")
                or structured_result.get("content")
                or structured_result.get("response")
            )

            for cfile in code_files:
                refined_steps.append(OSWorkflowStep(
                    step_id=f"agent-os-{step_counter}",
                    action_plan=ActionPlan(
                        operation="file.create",
                        target=cfile,
                        confidence=0.90,
                        reason=f"Coding Agent produced file: {cfile}",
                        source="UnifiedExecutor.refine_os_steps_from_agent_results",
                        parameters={
                            "agent": "Coding Agent",
                            "content": (
                                str(structured_code)
                                if structured_code is not None
                                else ""
                            ),
                            "confirmed": True,
                        },
                    ),
                    depends_on=(last_agent_step,) if last_agent_step else (),
                    agent_source="Coding Agent",
                ))
                step_counter += 1

            if structured_code and not code_files:
                language = str(structured_result.get("language", "")).lower()
                objective_text = plan.objective.lower()
                extension = "html" if "html" in language or "website" in objective_text else "txt"
                filename = "index.html" if extension == "html" else "generated.txt"
                refined_steps.append(OSWorkflowStep(
                    step_id=f"agent-os-{step_counter}",
                    action_plan=ActionPlan(
                        operation="file.create",
                        target=filename,
                        confidence=0.90,
                        reason="Coding Agent output bridged to a file creation step",
                        source="UnifiedExecutor.refine_os_steps_from_agent_results",
                        parameters={
                            "agent": "Coding Agent",
                            "content": str(structured_code),
                            "language": extension,
                            "confirmed": True,
                        },
                    ),
                    depends_on=(last_agent_step,) if last_agent_step else (),
                    agent_source="Coding Agent",
                ))
                step_counter += 1

            # Extract standalone fenced code blocks that don't have explicit paths
            code_blocks = re.findall(
                r'```(\w+)\n(.*?)```',
                code_text,
                re.DOTALL,
            )
            ext_map = {
                "python": "py", "py": "py",
                "javascript": "js", "js": "js",
                "typescript": "ts", "ts": "ts",
                "jsx": "jsx", "tsx": "tsx",
                "java": "java", "c": "c", "cpp": "cpp", "h": "h",
                "go": "go", "rust": "rs", "ruby": "rb",
                "bash": "sh", "shell": "sh", "sh": "sh",
                "powershell": "ps1", "ps1": "ps1",
                "yaml": "yaml", "yml": "yaml", "json": "json", "toml": "toml",
                "css": "css", "html": "html", "sql": "sql",
            }
            for lang, block in code_blocks:
                ext = ext_map.get(lang.lower())
                if ext and len(block.strip()) > 10:
                    # Generate a filename from language + first function/class or hash
                    first_line = block.strip().split('\n')[0][:60]
                    safe_name = re.sub(r'[^\w]', '_', first_line).strip('_')[:30]
                    fname = f"{safe_name or 'script'}.{ext}"
                    if fname not in code_files:
                        refined_steps.append(OSWorkflowStep(
                            step_id=f"agent-os-{step_counter}",
                            action_plan=ActionPlan(
                                operation="file.create",
                                target=fname,
                            confidence=0.90,
                            reason=f"Coding Agent produced {lang} code block",

                                source="UnifiedExecutor.refine_os_steps_from_agent_results",
                                parameters={
                                "agent": "Coding Agent",
                                "language": lang,
                                "content": block.strip(),
                                "confirmed": True,

                                },
                            ),
                            depends_on=(last_agent_step,) if last_agent_step else (),
                            agent_source="Coding Agent",
                        ))
                        step_counter += 1

        # --- Document Agent: extract document content and create document ops ---
        if "Document Agent" in all_data:
            doc_response = all_data["Document Agent"]
            doc_text = doc_response if isinstance(doc_response, str) else str(doc_response)

            # Extract document file paths
            doc_paths = re.findall(
                r'(?:[\w\\/:.~-]+[/\\])[\w.-]+\.(?:docx?|pdf|odt|rtf|tex|md|txt)',
                doc_text,
                re.IGNORECASE,
            )
            bare_doc_files = re.findall(
                r'\b([\w.-]+\.(?:docx?|pdf|odt|rtf|tex|md|txt))\b',
                doc_text,
                re.IGNORECASE,
            )
            all_doc_paths = list(dict.fromkeys(doc_paths + bare_doc_files))

            for dpath in all_doc_paths:
                ext = dpath.rsplit('.', 1)[-1].lower()
                if ext in ('docx', 'doc'):
                    operation = "document.create_docx"
                else:
                    operation = "file.create"
                refined_steps.append(OSWorkflowStep(
                    step_id=f"agent-os-{step_counter}",
                    action_plan=ActionPlan(
                        operation=operation,
                        target=dpath,
                        confidence=0.88,
                        reason=f"Document Agent referenced file: {dpath}",
                        source="UnifiedExecutor.refine_os_steps_from_agent_results",
                        parameters={"agent": "Document Agent"},
                    ),
                    depends_on=(last_agent_step,) if last_agent_step else (),
                    agent_source="Document Agent",
                ))
                step_counter += 1

            # Detect "create/write/export document" recommendations
            create_doc_patterns = [
                r'(?:create|generate|write|export|save)\s+(?:a\s+)?(?:document|docx?|report|summary|memo)',
                r'(?:create|generate|write|export)\s+(?:document\.create_docx|\.docx)',
            ]
            for pattern in create_doc_patterns:
                if re.search(pattern, doc_text, re.IGNORECASE):
                    target_name = "document.docx"
                    for p in all_doc_paths:
                        if p.lower().endswith(('.md', '.txt', '.odt')):
                            target_name = p.rsplit('.', 1)[0] + ".docx"
                            break
                    refined_steps.append(OSWorkflowStep(
                        step_id=f"agent-os-{step_counter}",
                        action_plan=ActionPlan(
                            operation="document.create_docx",
                            target=target_name,
                            confidence=0.85,
                            reason="Document Agent recommended creating document",
                            source="UnifiedExecutor.refine_os_steps_from_agent_results",
                            parameters={
                                "agent": "Document Agent",
                                "source_files": all_doc_paths[:5],
                            },
                        ),
                        depends_on=(last_agent_step,) if last_agent_step else (),
                        agent_source="Document Agent",
                    ))
                    step_counter += 1
                    break

        if re.search(
            r"\b(?:save|export|write|store)\b.*\bas\s+(?:an?\s+)?pdf\b",
            plan.objective,
            re.IGNORECASE,
        ):
            pdf_source = ""
            for result in reversed(agent_results):
                if not result.get("success"):
                    continue
                for key in ("response", "findings", "analysis", "content", "text", "result"):
                    value = result.get(key)
                    if value not in (None, ""):
                        pdf_source = str(value)
                        break
                if pdf_source:
                    break
            pdf_steps = [
                step for step in refined_steps
                if step.action_plan.operation == "document.create_pdf"
            ]
            if pdf_source and pdf_steps:
                pdf_step = pdf_steps[0]
                parameters = dict(pdf_step.action_plan.parameters)
                parameters.update({
                    "content": pdf_source,
                    "title": "Research Report",
                    "confirmed": True,
                })
                pdf_step.action_plan = pdf_step.action_plan.model_copy(
                    update={"parameters": parameters}
                )
            elif pdf_source:
                refined_steps.append(OSWorkflowStep(
                    step_id=f"agent-os-{step_counter}",
                    action_plan=ActionPlan(
                        operation="document.create_pdf",
                        target="research.pdf",
                        confidence=0.90,
                        reason="Agent output bridged to a PDF creation step",
                        source="UnifiedExecutor.refine_os_steps_from_agent_results",
                        parameters={
                            "content": pdf_source,
                            "title": "Research Report",
                            "confirmed": True,
                        },
                    ),
                    depends_on=(last_agent_step,) if last_agent_step else (),
                    agent_source=plan.agent_tasks[-1].agent_name if plan.agent_tasks else None,
                ))
                step_counter += 1

        coding_file_target = next(
            (
                str(step.action_plan.target)
                for step in refined_steps
                if (
                    step.action_plan.operation == "file.create"
                    and step.agent_source == "Coding Agent"
                    and step.action_plan.target
                )
            ),
            None,
        )

        # Always include original OS steps, wired with agent dependencies
        for step in plan.os_steps:
            if step.action_plan.operation == "document.create_pdf":
                existing = next(
                    (
                        candidate for candidate in refined_steps
                        if candidate.action_plan.operation == "document.create_pdf"
                    ),
                    None,
                )
                if existing is not None:
                    merged_parameters = dict(step.action_plan.parameters)
                    merged_parameters.update(existing.action_plan.parameters)
                    existing.action_plan = existing.action_plan.model_copy(
                        update={"parameters": merged_parameters}
                    )
                    continue
            if (
                coding_file_target
                and step.action_plan.operation == "application.open"
            ):
                application_name = (
                    step.action_plan.application
                    or step.action_plan.target
                )
                parameters = dict(step.action_plan.parameters)
                parameters["file_path"] = coding_file_target
                parameters["open_file"] = True
                step.action_plan = step.action_plan.model_copy(
                    update={
                        "target": coding_file_target,
                        "application": application_name,
                        "parameters": parameters,
                    }
                )
            if last_agent_step:
                step.depends_on = (last_agent_step,)
                step.agent_source = plan.agent_tasks[-1].agent_name if plan.agent_tasks else None
            refined_steps.append(step)

        return refined_steps


class UnifiedExecutor:
    """
    Executes mixed workflows: Level 2 agents + Level 3 OS operations.
    
    Pipeline:
        1. Plan mixed workflow (identify agents + OS steps)
        2. Execute Level 2 agents in dependency order
        3. Refine OS steps based on agent outputs
        4. Execute Level 3 OS workflow
        5. Verify and return unified result
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        workflow_engine: UniversalDesktopWorkflowEngine,
        session_state: SessionState,
        context_resolver: ContextResolver,
        decision_engine: WorkflowDecisionEngine,
    ):
        self.agent_registry = agent_registry
        self.workflow_engine = workflow_engine
        self.session_state = session_state
        self.context_resolver = context_resolver
        self.decision_engine = decision_engine

        self.agent_mapper = AgentCapabilityMapper(agent_registry)
        self.workflow_planner = MixedWorkflowPlanner(
            agent_mapper=self.agent_mapper,
            decision_engine=decision_engine,
            context_resolver=context_resolver,
        )

    def execute(self, objective: str) -> MixedWorkflowResult:
        """Execute a complete mixed intelligence + OS workflow."""
        # 1. Plan the mixed workflow
        plan = self.workflow_planner.plan(objective)

        # Initialize session state task tracking
        if self.session_state:
            agent_step_infos = [
                {"step_id": t.step_id, "agent_name": t.agent_name, "operation": "agent_task"}
                for t in plan.agent_tasks
            ]
            self.session_state.start_task(
                task_id=plan.workflow_id,
                objective=objective,
                steps=agent_step_infos,
            )

        # 2. Execute Level 2 agents
        agent_results = self._execute_agents(plan.agent_tasks)

        # 3. Refine OS steps based on agent results
        if plan.os_steps:
            refined_os_steps = self.workflow_planner.refine_os_steps_from_agent_results(
                plan, agent_results
            )
        else:
            refined_os_steps = []

        # 4. Execute Level 3 OS workflow if any OS steps
        os_results = []
        if refined_os_steps:
            workflow_plan = self._build_workflow_plan(refined_os_steps, objective)
            os_result = self.workflow_engine.execute(workflow_plan)
            os_results = list(os_result.steps) if os_result.steps else []
            final_verified = os_result.final_verified
            os_success = os_result.success
            os_message = os_result.message
            os_error = os_result.error
        else:
            final_verified = True
            os_success = True
            os_message = "No OS operations required."
            os_error = None

        # 5. Check agent success
        agent_success = all(r.get("success", False) for r in agent_results)

        overall_success = agent_success and os_success
        overall_verified = overall_success and final_verified

        if not overall_success:
            errors = []
            for r in agent_results:
                if not r.get("success"):
                    errors.append(f"{r.get('agent', 'Agent')}: {r.get('error', 'Failed')}")
            if os_error:
                errors.append(f"OS: {os_error}")
            error_msg = "; ".join(errors) if errors else "Workflow failed"
        else:
            error_msg = None

        return MixedWorkflowResult(
            success=overall_success,
            objective=objective,
            agent_results=agent_results,
            os_results=os_results,
            final_verified=overall_verified,
            message=os_message if overall_success else f"Workflow partially failed: {error_msg}",
            error=error_msg,
            metadata={
                "agent_count": len(plan.agent_tasks),
                "os_step_count": len(refined_os_steps),
                "agents_executed": [t.agent_name for t in plan.agent_tasks],
            },
        )

    def _execute_agents(self, agent_tasks: List[AgentTask]) -> List[Dict[str, Any]]:
        """Execute Level 2 agents in dependency order."""
        results = []
        completed = set()

        # Simple topological execution (agents already ordered by planner)
        for task in agent_tasks:
            # Check dependencies
            if not all(dep in completed for dep in task.depends_on):
                results.append({
                    "agent": task.agent_name,
                    "task": task.task,
                    "success": False,
                    "error": f"Dependency not met: {task.depends_on}",
                    "step_id": task.step_id,
                })
                continue

            agent = self.agent_registry.get_agent(task.agent_name)
            if not agent:
                results.append({
                    "agent": task.agent_name,
                    "task": task.task,
                    "success": False,
                    "error": f"Agent not found: {task.agent_name}",
                    "step_id": task.step_id,
                })
                continue

            try:
                result = agent.execute(task.task, task.context)
                result["step_id"] = task.step_id
                result["agent"] = task.agent_name
                results.append(result)

                if result.get("success"):
                    completed.add(task.step_id)
                    # Store in session state for context resolution
                    if self.session_state:
                        self.session_state._task_history[-1].metadata[f"agent_{task.agent_name}_result"] = result
            except Exception as exc:
                results.append({
                    "agent": task.agent_name,
                    "task": task.task,
                    "success": False,
                    "error": str(exc),
                    "step_id": task.step_id,
                })

        return results

    def _build_workflow_plan(
        self,
        os_steps: List[OSWorkflowStep],
        objective: str,
    ) -> WorkflowPlan:
        """Convert OSWorkflowSteps to WorkflowPlan."""
        from genesis_os.workflow_models import WorkflowStep

        workflow_steps = []
        for os_step in os_steps:
            # OS steps in unified executor are already sequenced after agents
            # Don't include agent dependencies in the OS workflow
            step = WorkflowStep(
                step_id=os_step.step_id,
                plan=os_step.action_plan,
                depends_on=(),  # Agent dependencies handled by unified executor
                verification_required=True,
                max_retries=0,
                retryable=False,
                metadata={
                    "agent_source": os_step.agent_source,
                },
            )
            workflow_steps.append(step)

        return WorkflowPlan(
            objective=objective,
            steps=tuple(workflow_steps),
            workflow_id=f"mixed-{hash(objective)}",
        )


# Convenience function for integration
def create_unified_executor(
    agent_registry: AgentRegistry,
    workflow_engine: UniversalDesktopWorkflowEngine,
    session_state: SessionState,
    context_resolver: ContextResolver,
    decision_engine: WorkflowDecisionEngine,
) -> UnifiedExecutor:
    """Create a unified executor with all dependencies."""
    return UnifiedExecutor(
        agent_registry=agent_registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=context_resolver,
        decision_engine=decision_engine,
    )