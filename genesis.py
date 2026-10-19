"""
Genesis OS - Unified Runtime Entry Point

LEVEL 1
-------
Brain
Memory
Conversation
Reasoning
Emotion
Personality
Knowledge
AI Engine

LEVEL 2
-------
Agent Discovery
Agent Registry
Shared Agent Context
Agent Orchestrator
Single-Agent Execution
Multi-Agent Execution
Parallel Execution
Result Aggregation

LEVEL 3
-------
AI Operating System
Application Intelligence

UNIFIED INTELLIGENCE
--------------------
Genesis intelligently decides whether a request should use:

    1. Level 1 conversation/core intelligence
    2. Level 2 single specialized agent
    3. Level 2 multi-agent workflow
    4. Level 3 operating-system capability

Everything runs inside ONE Genesis process and ONE session.

The WorkflowDecisionEngine remains the primary decision layer.
GenesisOS does not create a competing keyword router.
"""

# =========================================================
# LEVEL 3
# =========================================================


# =========================================================
# LEVEL 1
# =========================================================
import re
import sys
from dataclasses import replace as dataclass_replace
from pathlib import Path
from genesis_os.action_plan import ActionPlan
from genesis_os.action_executor import ActionExecutor
from genesis_os.desktop_workflow import DesktopWorkflowExecutor
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.target_discovery import TargetDiscovery
from genesis_os.application_target_provider import ApplicationTargetProvider
from genesis_os.file_target_provider import FileTargetProvider
from genesis_os.folder_target_provider import FolderTargetProvider
from genesis_os.workflow_target_resolver import WorkflowTargetResolver
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.capability_resolver import CapabilityResolver
from genesis_os.workflow_capability import WorkflowCapabilityResolver
from memory.memory import MemoryManager
from memory.long_term_memory import LongTermMemory
from brain.brain import Brain
from conversation.conversation import ConversationEngine
from genesis_os.workflow_decomposer import (
    WorkflowDecomposer,
)
from genesis_os.context_resolver import ContextResolver
from genesis_os.unified_executor import create_unified_executor
from genesis_os.objective_understanding import (
    ObjectiveUnderstanding,
    ObjectiveStepIntent,
    ObjectiveUnderstandingResult,
)
from genesis_os.session_context import (
    SessionContextBinder,
)
from genesis_os.llm_intent_resolver import (
    LLMIntentResolver,
)
from genesis_os.language_normalizer import (
    LanguageNormalizer,
)
from genesis_os.session_state import SessionState
from genesis_os.entity_history import (
    EntityHistory,
    EntityType,
    EntityAction,
)
from genesis_os.target_models import ConversationContext

# =========================================================
# LEVEL 2
# =========================================================

from agent_context.context import AgentContext
from agents.agent_discovery import AgentDiscovery
from agents.agent_registry import AgentRegistry
from agents.agent_orchestrator import AgentOrchestrator
from agents.multi_agent_executor import MultiAgentExecutor
from agents.result_aggregator import ResultAggregator

# =========================================================
# UNIFIED DECISION
# =========================================================

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.os_manager import OSManager
from runtime.audit import ExecutionAudit
from runtime.genesis_runtime import GenesisRuntime


# =========================================================
# CONFIRMATION PROMPT HELPERS
# =========================================================

# Trailing fragments in a capability descriptor's
# ``description`` field that are accurate but unfit for a
# user-facing confirmation prompt. They read like system
# documentation rather than an action the user is approving.
_DESCRIPTOR_NOISE_TRAILERS = (
    "Read-only.",
    "Read-only",
    "Requires confirmation.",
    "Requires confirmation",
    "Requires user confirmation.",
    "Requires user confirmation",
    "Confirmation required.",
    "Confirmation required",
    "Gated.",
    "Gated",
)


def _strip_descriptor_noise(description: str) -> str:
    """
    Return ``description`` with trailing technical
    annotations ("Read-only.", "Requires confirmation.")
    stripped, so the result reads naturally as a
    confirmation prompt.

    Only trailing sentences are removed; leading and
    mid-sentence technical terms are preserved because
    they usually carry the actual meaning of the
    capability (e.g. "Open a resolved desktop
    application.").
    """

    if not description:
        return ""

    text = description.strip()

    if not text:
        return ""

    trailers = tuple(
        t.lower().rstrip(". ") for t in
        _DESCRIPTOR_NOISE_TRAILERS
    )

    while True:
        lowered = text.lower()
        matched = None
        for trailer in trailers:
            if (
                lowered.endswith(trailer)
                or lowered.endswith(trailer + ".")
            ):
                matched = trailer
                break
        if matched is None:
            break

        # Find the sentence boundary immediately preceding
        # the trailer. The trailer is at the end of the
        # string, so the boundary is the last occurrence of
        # ". " / "! " / "? " that lies BEFORE the start of
        # the trailer sentence.
        trailer_pos = lowered.rfind(matched)
        if trailer_pos <= 0:
            # The whole text is just the trailer; drop it.
            text = ""
            break

        boundary = -1
        for sep in (". ", "! ", "? "):
            idx = lowered.rfind(sep, 0, trailer_pos)
            if idx != -1 and idx > boundary:
                boundary = idx
        if boundary == -1:
            # No sentence boundary found — the trailer is
            # embedded mid-sentence; leave it untouched
            # rather than mutilate the description.
            break

        # Drop everything from the boundary (inclusive of
        # the boundary period) to the end.
        text = text[:boundary].rstrip().rstrip(".!?")

    return text.strip().rstrip(".")


def _friendly_from_operation_id(operation: str) -> str:
    """
    Build a generic, human-friendly phrase from a
    capability id when no proper plain-language
    descriptor is available. The raw id MUST NOT appear
    in the returned string.

    "cleanup.recycle_bin_query" -> "check the recycle bin"
    "system.battery_query"       -> "query system battery"
    """

    if not operation:
        return "perform an OS action"

    parts = operation.split(".")

    if len(parts) >= 2:
        category = parts[0].replace("_", " ").strip()
        action = "_".join(parts[1:]).replace("_", " ").strip()
    else:
        category = ""
        action = parts[0].replace("_", " ").strip()

    if action.startswith(("query ", "get ", "read ", "fetch ")):
        action_body = action.split(" ", 1)[1].strip()
        if category:
            return f"check the {action_body} from {category}"
        return f"check the {action_body}"

    if action.startswith("set "):
        action_body = action[4:].strip()
        if category:
            return f"set {category} {action_body}"
        return f"set {action_body}"

    if action.startswith(("create ", "make ")):
        action_body = action.split(" ", 1)[1].strip()
        if category:
            return f"create a new {category} {action_body}"
        return f"create a new {action_body}"

    if action.startswith(("delete ", "drop ")):
        action_body = action.split(" ", 1)[1].strip()
        if category:
            return f"delete the {category} {action_body}"
        return f"delete the {action_body}"

    if action.startswith(("list ", "show ", "find ")):
        action_body = action.split(" ", 1)[1].strip()
        if category:
            return f"list {category} {action_body}"
        return f"list {action_body}"

    if action.startswith("empty "):
        action_body = action[6:].strip()
        if category:
            return f"empty the {category} {action_body}"
        return f"empty the {action_body}"

    if action:
        if category:
            return f"{action} {category}"
        return action

    if category:
        return f"perform a {category} action"

    return "perform an OS action"


class _ProductionRuntimeBridge:
    def __init__(self, decision_engine):
        self.decision_engine = decision_engine

    def classify_request(self, text):
        return self.decision_engine.decide(text)

    def handle(self, text):
        return {
            "success": False,
            "error": "Production Level 3 execution is owned by GenesisOS.",
            "task": text,
        }



def announce_boundary_state() -> str:
    """Load Genesis config explicitly, then print the boundary state.

    Added 2026-10-08 (F5 follow-up 1). Previously the workspace
    boundary was armed only as a side effect of AIEngine.__init__
    calling load_dotenv(), so a bare GenesisOS process ran UNARMED
    even though .env declared a root. Arming is now an explicit,
    intentional step at startup, and the resulting state is printed.

    Loading happens here and NOT inside workspace_root(), because
    auto-loading would make the unarmed path unreachable and no test
    could ever verify it.
    """
    try:
        from genesis_os.genesis_config import load_genesis_config

        load_genesis_config()
    except Exception:
        # A missing or unreadable .env must not stop Genesis from
        # starting; it simply runs unarmed.
        pass
    from genesis_os.workspace_boundary import boundary_banner_text

    banner = boundary_banner_text()
    print(banner)
    return banner


class GenesisOS:
    """
    Unified Genesis runtime.

    Level 1:
        Core intelligence

    Level 2:
        Specialized agent intelligence

    Level 3:
        Operating-system capabilities
    """

    # =====================================================
    # INITIALIZATION
    # =====================================================

    def __init__(self):

        print(
            "[Genesis] Initializing unified runtime..."
        )

        # -------------------------------------------------
        # CONSOLE ENCODING SAFETY
        #
        # Windows consoles default to a legacy codepage; the
        # AI layers may emit unicode glyphs (arrows in model
        # output). Replace instead of crash.
        # -------------------------------------------------

        import sys as _sys

        for stream_name in ("stdout", "stderr"):

            stream = getattr(_sys, stream_name, None)

            if stream is not None and hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(errors="replace")
                except Exception:
                    pass

        # -------------------------------------------------
        # LEVEL 1 — CORE INTELLIGENCE
        # -------------------------------------------------

        self.brain = Brain()

        self.conversation = (
            ConversationEngine()
        )

        self.memory = MemoryManager()

        profile = self.memory.load_profile()

        if profile == {}:

            profile["user_name"] = "Unknown"

            self.memory.save_profile(
                profile
            )

        # -------------------------------------------------
        # LEVEL 2 — SHARED AGENT CONTEXT
        # -------------------------------------------------

        self.context = AgentContext()

        # -------------------------------------------------
        # LEVEL 2 — DISCOVERY
        # -------------------------------------------------

        self.discovery = AgentDiscovery()

        self.registry = AgentRegistry()

        # Share a single AIEngine across every agent so we
        # don't reload ``.env`` nine times or print nine
        # status banners. The Brain owns the canonical
        # AIEngine instance; agents receive a reference so
        # their ``self.ai`` is the same object.
        try:
            shared_ai = getattr(self.brain, "ai_engine", None)
        except Exception:
            shared_ai = None

        self.agents = (
            self.discovery.discover(ai_engine=shared_ai)
        )

        for agent in self.agents:

            self.registry.register(
                agent
            )

        # -------------------------------------------------
        # LEVEL 2 — ORCHESTRATION
        # -------------------------------------------------

        self.orchestrator = (
            AgentOrchestrator(
                self.registry,
                self.context
            )
        )

        self.executor = (
            MultiAgentExecutor(
                self.registry,
                self.context
            )
        )

        self.aggregator = (
            ResultAggregator(
                self.context
            )
        )

        # -------------------------------------------------
        # UNIFIED WORKFLOW DECISION
        # -------------------------------------------------
        #
        # WorkflowDecisionEngine remains the SINGLE
        # decision layer for:
        #
        # Level 1
        # Level 2 single-agent
        # Level 2 multi-agent
        # Level 3 OS capability
        #
        # We do NOT create another router here.
        #

        self.capability_registry = CapabilityRegistry()
        self.capability_resolver = CapabilityResolver(
            self.capability_registry
        )
        self.workflow_decision = (
            WorkflowDecisionEngine(
                registry=self.registry,
                context=self.context,
                conversation=self.conversation,
                memory=self.memory,
                ai_engine=self.brain.ai_engine,
                capability_resolver=self.capability_resolver,
            )
        )

        # -------------------------------------------------
        # LEVEL 3 — AI OPERATING SYSTEM
        # -------------------------------------------------

        self.os_manager = OSManager()
        self.action_executor = ActionExecutor(self.os_manager)

        from genesis_os.agent_framework_adapter import (
            AgentFrameworkAdapter,
        )

        self.agent_framework_adapter = AgentFrameworkAdapter(
            self.action_executor
        )

        self.desktop_workflow = DesktopWorkflowExecutor(self.action_executor)
        self.universal_workflow = UniversalDesktopWorkflowEngine(
            self.action_executor,
            os_manager=self.os_manager,
        )
        self.execution_audit = ExecutionAudit()
        self.genesis_runtime = GenesisRuntime(
            brain=self.brain,
            conversation=self.conversation,
            memory=self.memory,
            ai_engine=self.brain.ai_engine,
            agent_bridge=_ProductionRuntimeBridge(self.workflow_decision),
            os_manager=self.os_manager,
            audit=self.execution_audit,
            action_executor=self.action_executor,
            workflow_engine=self.universal_workflow,
        )
        self.workflow_decomposer = WorkflowDecomposer(
            capability_registry=self.capability_registry,
            capability_resolver=self.capability_resolver,
        )
        self.target_discovery = TargetDiscovery(
            file_provider=FileTargetProvider(),
            folder_provider=FolderTargetProvider(),
            application_provider=ApplicationTargetProvider(self.os_manager.applications.discovery),
        )
        self.workflow_target_resolver = WorkflowTargetResolver(self.target_discovery)
        self.workflow_capability_resolver = WorkflowCapabilityResolver(self.capability_resolver)
        self.objective_understanding = ObjectiveUnderstanding(
            self.workflow_decision
        )

        # -------------------------------------------------
        # COMPOUND TASK ROUTER (Level 3.17)
        # -------------------------------------------------
        # Bridges the WorkflowDecisionEngine (single L3 intent)
        # with the UniversalDesktopWorkflowEngine (multi-step
        # workflow) so compound natural-language requests such
        # as "open chrome, go to github, search langchain" are
        # decomposed into independently executable OS steps
        # rather than silently collapsed to the first action.
        from agents.compound_task_router import CompoundTaskRouter
        self.compound_task_router = CompoundTaskRouter(
            objective_understanding=self.objective_understanding,
            workflow_decomposer=self.workflow_decomposer,
        )
        self.session_context_binder = (
            SessionContextBinder(
                self.workflow_decision
            )
        )

        self.llm_intent_resolver = (
            LLMIntentResolver(
                ai_engine=self.brain.ai_engine,
                decision_engine=self.workflow_decision,
            )
        )
        self._pending_llm_action = None
        self.language_normalizer = LanguageNormalizer(
            ai_engine=self.brain.ai_engine,
        )

        # -----------------------------------------------------
        # LONG-TERM MEMORY
        #
        # Genesis genuinely knows the user: facts are extracted
        # from every turn, persisted, and injected into answers
        # across all levels.
        # -----------------------------------------------------

        self.long_term_memory = LongTermMemory(
            memory_manager=self.memory,
            ai_engine=self.brain.ai_engine,
        )

        # -------------------------------------------------
        # SESSION STATE (Level 3.9)
        # Centralized OS state: current application, browser,
        # folder, file, clipboard, task state.
        # -------------------------------------------------

        self.session_state = SessionState(
            os_manager=self.os_manager
        )

        # -------------------------------------------------
        # ENTITY HISTORY (Level 3.9+)
        # Tracks every entity created/opened/modified/
        # referenced across ALL levels for pronoun and
        # reference resolution.
        # -------------------------------------------------

        self.entity_history = EntityHistory()
        self.conversation_context = ConversationContext()
        self.target_discovery.context = self.conversation_context
        self.workflow_target_resolver.context = self.conversation_context

        # -------------------------------------------------
        # INJECT SESSION CONTEXT INTO EXECUTOR
        # -------------------------------------------------

        self.executor.set_session_context(
            session_state=self.session_state,
            entity_history=self.entity_history,
        )

        self.context_resolver = ContextResolver(
            session_state=self.session_state,
            decision_engine=self.workflow_decision,
        )
        self.unified_executor = create_unified_executor(
            agent_registry=self.registry,
            workflow_engine=self.universal_workflow,
            session_state=self.session_state,
            context_resolver=self.context_resolver,
            decision_engine=self.workflow_decision,
        )

        self.session_context_binder.set_entity_history(
            self.entity_history
        )

        # -------------------------------------------------
        # RUNTIME STATE
        # -------------------------------------------------

        self.running = True

        print(
            "[Genesis] Unified runtime initialized."
        )

    # =====================================================
    # FALLBACK BROWSER (timeout / init failure path)
    # =====================================================

    @staticmethod
    def _build_minimal_browser():
        """Build a BrowserManager with only the stdlib provider.

        Called when BrowserManager() construction exceeds the
        timeout or raises.  ``webbrowser.open()`` still works;
        Selenium/Playwright automation is unavailable.
        """
        from genesis_os.browser_manager import (
            BrowserManager,
            WebBrowserProvider,
        )

        bm = object.__new__(BrowserManager)
        bm._providers = [WebBrowserProvider()]
        bm._sessions = {}
        bm._default_session_id = "default"
        bm._registry = None
        bm._ensure_session(bm._default_session_id)

        print(
            "[Genesis] Minimal browser ready "
            "(Selenium/Playwright probes skipped)."
        )
        return bm

    # =====================================================
    # STARTUP DISPLAY
    # =====================================================


    @property
    def browser_degraded(self):
        """True when the browser manager is running webbrowser-only
        because a provider probe timed out.

        Exposed so a degraded runtime is observable rather than silent.
        `show_startup` prints it; callers can assert on it.
        """
        browser = getattr(self.os_manager, "browser", None)
        return bool(getattr(browser, "degraded", False))

    @property
    def browser_degraded_reason(self):
        browser = getattr(self.os_manager, "browser", None)
        return getattr(browser, "degraded_reason", None)

    @property
    def browser_provider_names(self):
        browser = getattr(self.os_manager, "browser", None)
        names = getattr(browser, "provider_names", None)
        return list(names) if names else []

    def show_startup(self):
        announce_boundary_state()


        print(
            "\n" + "=" * 68
        )

        print(
            "                         GENESIS OS"
        )

        print(
            "                  AI OPERATING SYSTEM"
        )

        print(
            "=" * 68
        )

        # -------------------------------------------------
        # LEVEL 1
        # -------------------------------------------------

        print()

        print(
            "LEVEL 1 — CORE INTELLIGENCE"
        )

        print(
            "  Brain ......................... ONLINE"
        )

        print(
            "  Memory ........................ ONLINE"
        )

        print(
            "  Conversation Engine ........... ONLINE"
        )

        print(
            "  AI Engine ...................... ONLINE"
        )

        # -------------------------------------------------
        # LEVEL 2
        # -------------------------------------------------

        print()

        print(
            "LEVEL 2 — AI AGENT SYSTEM"
        )

        # A partially-constructed runtime (GenesisOS.__new__ in tests) has no
        # discovery object at all, so this must not raise.
        discovery = getattr(self, "discovery", None)
        discovery_failures = ()
        if discovery is not None:
            discovery_failures = (
                getattr(discovery, "import_failures", ())
                + getattr(discovery, "init_failures", ())
            )

        if discovery_failures:
            print(
                "  Agent Discovery ............... DEGRADED "
                f"({len(discovery_failures)} module/class failure(s))"
            )
            for name, error in discovery_failures:
                print(
                    f"    ! {name}: {error}"
                )
        else:
            print(
                "  Agent Discovery ............... ONLINE"
            )

        print(
            f"  Agents discovered ............. "
            f"{len(self.agents)}"
        )

        print(
            f"  Agents registered ............. "
            f"{self.registry.count()}"
        )

        print(
            "  Shared Context ................ ONLINE"
        )

        print(
            "  Orchestrator .................. ONLINE"
        )

        print(
            "  Multi-Agent Executor .......... ONLINE"
        )

        print(
            "  Parallel Executor ............. ONLINE"
        )

        print(
            "  Result Aggregator ............. ONLINE"
        )

        # -------------------------------------------------
        # LEVEL 3
        # -------------------------------------------------

        print()

        print(
            "LEVEL 3 — AI OPERATING SYSTEM"
        )

        os_status = (
            self.os_manager.status()
        )

        print(
            "  OS Core ....................... "
            f"{'ONLINE' if os_status.get('level') == 3 else 'OFFLINE'}"
        )

        print(
            "  Application Intelligence ...... "
            f"{'ONLINE' if os_status.get('application_intelligence') else 'OFFLINE'}"
        )

        print(
            "  File Intelligence ............. "
            f"{'ONLINE' if os_status.get('file_intelligence') else 'NOT IMPLEMENTED'}"
        )

        print(
            "  Folder Intelligence ........... "
            f"{'ONLINE' if os_status.get('folder_intelligence') else 'NOT IMPLEMENTED'}"
        )

        print(
            "  Process Intelligence .......... "
            f"{'ONLINE' if os_status.get('process_intelligence') else 'NOT IMPLEMENTED'}"
        )

        print(
            "  System Intelligence ........... "
            f"{'ONLINE' if os_status.get('system_intelligence') else 'NOT IMPLEMENTED'}"
        )

        print(
            "  Document Intelligence ......... "
            f"{'ONLINE' if os_status.get('document_intelligence') else 'NOT IMPLEMENTED'}"
        )

        # Browser status. A DEGRADED line means the advanced providers
        # (playwright / selenium) were NOT registered because their
        # availability probes did not finish inside the bounded wait,
        # NOT because the drivers are known to be missing. It is
        # reported rather than hidden: webbrowser can still open pages,
        # but anything needing a real driver is unavailable right now,
        # and the provider caches retry after a TTL.
        browser_names = (
            self.browser_provider_names
        )
        if (
            self.browser_degraded
        ):
            print(
                f"  Browser Automation ............ DEGRADED: "
                f"{', '.join(browser_names) or 'webbrowser only'} "
                f"({self.browser_degraded_reason})"
            )
        else:
            print(
                "  Browser Automation ............ "
                f"{', '.join(browser_names) or 'webbrowser only'}"
            )

        # -------------------------------------------------
        # AGENTS
        # -------------------------------------------------

        print()

        print(
            "  Available Agents:"
        )

        for agent in (
            self.registry.get_all_agents()
        ):

            print(
                f"    ✓ {agent.name}"
            )

        # -------------------------------------------------
        # UNIFIED INTELLIGENCE
        # -------------------------------------------------

        print()

        print(
            "UNIFIED INTELLIGENCE"
        )

        print(
            "  Workflow Decision Engine ...... ONLINE"
        )

        print(
            "  Level 1 → Level 2 Routing ..... ONLINE"
        )

        print(
            "  Level 2 → Level 3 Routing ..... ONLINE"
        )

        print(
            "  Single-Agent Workflows ........ ONLINE"
        )

        print(
            "  Multi-Agent Workflows ......... ONLINE"
        )

        print(
            "  Shared Result Context ......... ONLINE"
        )

        print(
            "  Genesis Synthesis ............. ONLINE"
        )

        print()

        print(
            "=" * 68
        )

        print(
            "                  GENESIS OS — READY"
        )

        print(
            "=" * 68
        )

        print(
            "Type 'help' for commands or 'exit' to close Genesis."
        )

    # =====================================================
    # INTELLIGENT REQUEST CLASSIFICATION
    # =====================================================

    def classify(self, text):
        """
        Delegate workflow classification to the
        WorkflowDecisionEngine.

        Supported levels:

            Level 1:
                conversation

            Level 2:
                single_agent

            Level 2:
                multi_agent

            Level 3:
                os
        """

        decision = (
            self.genesis_runtime.classify(
                text
            )
        )

        # -------------------------------------------------
        # INVALID DECISION SAFETY
        # -------------------------------------------------

        if not isinstance(
            decision,
            dict
        ):

            return {
                "level": 1,
                "mode": "conversation",
                "agent": None,
                "agents": [],
                "task": text,
                "reason": (
                    "Decision engine returned "
                    "an invalid result."
                )
            }

        # -------------------------------------------------
        # DEFAULT VALUES
        # -------------------------------------------------

        decision.setdefault(
            "level",
            1
        )

        decision.setdefault(
            "mode",
            "conversation"
        )

        decision.setdefault(
            "agent",
            None
        )

        decision.setdefault(
            "agents",
            []
        )

        decision.setdefault(
            "task",
            text
        )

        decision.setdefault(
            "reason",
            "Workflow decision completed."
        )

        # -------------------------------------------------
        # LEVEL 3 DEFAULTS
        # -------------------------------------------------

        decision.setdefault(
            "intent",
            None
        )

        decision.setdefault(
            "application",
            None
        )

        # -------------------------------------------------
        # NORMALIZE AGENT LIST
        # -------------------------------------------------

        agents = decision.get(
            "agents"
        )

        if agents is None:

            agents = []

        elif isinstance(
            agents,
            str
        ):

            agents = [
                agents
            ]

        elif not isinstance(
            agents,
            list
        ):

            try:

                agents = list(
                    agents
                )

            except TypeError:

                agents = []

        decision["agents"] = agents

        # -------------------------------------------------
        # NORMALIZE LEVEL
        # -------------------------------------------------

        try:

            decision["level"] = int(
                decision["level"]
            )

        except (
            TypeError,
            ValueError
        ):

            decision["level"] = 1

        if decision["level"] not in (
            1,
            2,
            3
        ):

            decision["level"] = 1

        # -------------------------------------------------
        # VALID MODES
        # -------------------------------------------------

        valid_modes = {
            "conversation",
            "single_agent",
            "multi_agent",
            "os"
        }

        if (
            decision["mode"]
            not in valid_modes
        ):

            if decision["level"] == 3:

                decision["mode"] = "os"

            elif len(agents) >= 2:

                decision["mode"] = (
                    "multi_agent"
                )

            elif agents:

                decision["mode"] = (
                    "single_agent"
                )

            else:

                decision["mode"] = (
                    "conversation"
                )

        # -------------------------------------------------
        # LEVEL 3 MUST REMAIN LEVEL 3
        # -------------------------------------------------
        #
        # This must happen BEFORE the Level 2
        # multi-agent consistency correction.
        #
        # An OS request should never be converted
        # into a Level 2 workflow merely because
        # an agent keyword happens to appear.
        #

        if (
            decision["level"] == 3
            or decision["mode"] == "os"
        ):

            decision["level"] = 3
            decision["mode"] = "os"

            decision["agent"] = None
            decision["agents"] = []

            return decision

        # -------------------------------------------------
        # LEVEL 2 CONSISTENCY
        # -------------------------------------------------

        if len(agents) >= 2:

            decision["level"] = 2
            decision["mode"] = (
                "multi_agent"
            )

            decision["agent"] = None

        elif (
            decision["level"] == 2
            and decision["mode"]
            == "single_agent"
            and not decision.get("agent")
            and agents
        ):

            decision["agent"] = (
                agents[0]
            )

        elif (
            decision["level"] == 2
            and decision["mode"]
            == "conversation"
        ):

            if agents:

                decision["mode"] = (
                    "multi_agent"
                    if len(agents) >= 2
                    else "single_agent"
                )

                decision["agent"] = (
                    None
                    if len(agents) >= 2
                    else agents[0]
                )

            else:

                decision["level"] = 1
                decision["mode"] = (
                    "conversation"
                )

        return decision

    # =====================================================
    # LEVEL 3 — SEMANTIC TARGET RESOLUTION
    # =====================================================

    # Operations whose target is a natural-language description
    # rather than a literal path. These targets MUST pass through
    # the Level 3.8.4 discovery/resolution pipeline before
    # execution. Operations that create new targets (folder.create,
    # file.create) and query-style operations (file.search) are
    # intentionally excluded.
    SEMANTIC_TARGET_OPERATIONS = frozenset({
        "folder.open",
        "folder.inspect",
        "folder.organize",
        "file.open",
        "file.inspect",
        "file.read",
        "file.hash",
        "file.copy",
        "file.move",
        "file.rename",
    })

    def _resolve_semantic_target(self, plan):
        """
        Resolve a natural-language plan target into a concrete
        real-world target through the existing Level 3.8.4
        TargetDiscovery/TargetResolver pipeline.

        A semantic name such as "downloads" must resolve to the
        user's actual Windows Downloads folder; it must never be
        treated as a literal relative path.

        When resolution is not successful the original plan is
        returned unchanged so execution can fail transparently
        instead of guessing.
        """

        if not isinstance(plan, ActionPlan):
            return plan

        if plan.operation not in self.SEMANTIC_TARGET_OPERATIONS:
            return plan

        if not plan.target or not str(plan.target).strip():
            return plan

        try:
            query = (
                self.target_discovery
                .build_query_from_action_plan(
                    plan
                )
            )

            resolution = (
                self.target_discovery
                .discover_and_resolve(
                    query
                )
            )

        except Exception as error:

            print(
                "[Genesis OS] "
                "Semantic target resolution "
                f"unavailable: {error}"
            )

            return plan

        if resolution is None or not resolution.successful:
            return None

        resolved = resolution.resolved

        if resolved is None:
            return None

        # Do not downgrade an already-concrete literal target
        # with a weaker guess.
        if Path(plan.target).exists() and resolved.confidence < 0.90:
            return plan

        print(
            "[Genesis OS] "
            f"Resolved target '{plan.target}' -> "
            f"{resolved.value} "
            f"(confidence {resolved.confidence:.2f})"
        )

        return dataclass_replace(
            plan,
            target=resolved.value,
        )

    def _resolve_level3_capability(self, classification):
        if not isinstance(classification, dict):
            return None
        if classification.get("level") != 3:
            return classification
        operation = (
            classification.get("operation")
            or classification.get("intent")
        )
        if not operation or operation == "compound.os":
            return classification
        resolver = getattr(self, "capability_resolver", None)
        if resolver is None:
            return classification
        parameters = classification.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        resolution = resolver.resolve_operation(
            operation,
            description=str(classification.get("task", "")),
            inputs=parameters.keys(),
        )
        if not resolution.resolved:
            return None
        from genesis_os.capability_resolution import (
            capability_resolution_metadata,
        )
        updated = dict(classification)
        updated["parameters"] = dict(parameters)
        updated["parameters"]["_capability_resolution"] = (
            capability_resolution_metadata(resolution)
        )
        return updated

    # =====================================================
    # HUMAN APPROVAL SEAM (Directive 9A)
    # =====================================================
    #
    # SEAM TRACE, recorded before any edit.
    #
    #   genesis.py _ActionPlan.from_decision()  builds a plan
    #     -> stored in self._pending_llm_action["plan"]
    #     -> _execute_pending_action() pops it, records the user's
    #        "yes" as `source`, and then DISCARDS the plan: it calls
    #        _handle_level3_request(task, confirmed_decision), which
    #        re-derives everything from text + classification.
    #     -> _handle_level3_request -> run_level3
    #     -> run_level3 builds a FRESH ActionPlan (line ~1465) and
    #        resolves its semantic target (line ~1489)
    #     -> genesis_runtime.execute_audited(plan=plan)
    #     -> GenesisRuntime.execute_audited -> executor.execute(plan)
    #     -> action_executor.execute reads
    #            getattr(plan, "authorization")            (line ~801)
    #            getattr(plan, "authorization_arguments")  (line ~802)
    #
    # The ONLY writer of those two fields in the entire codebase is
    # action_plan.attach_authorization(plan, grant, arguments), which
    # returns a NEW plan via model_copy. Before Directive 9A it had ZERO
    # product callers -- only tests -- so both fields were always None
    # and every Tier 1 operation returned confirmation_required forever.
    #
    # WHY THE SEAM IS HERE AND NOT IN _execute_pending_action:
    # _execute_pending_action throws the plan away, so attaching a grant
    # to it would authorise an object that is never executed. The only
    # point where the plan actually executed is run_level3, after the
    # target has been resolved and before execute_audited. Placing it
    # here also covers the direct Level 3 path, not just the pending
    # confirm path, so there is exactly ONE place that can open the gate.
    #
    # NO CONTRACT CHANGE WAS NEEDED. attach_authorization already exists
    # and already returns a plan; execute_audited already accepts any
    # plan. The executor, adapter and ActionPlan are all untouched.

    def _authorize_plan_for_execution(self, plan):
        """Return ``(plan_to_execute, denial_message_or_None)``.

        Asks the real human-approval channel for the operations the
        executor will gate, and attaches a genuine AuthorizationGrant to
        the plan when -- and only when -- a human approved exactly these
        arguments on a real TTY.

        Nothing here is reachable by the model: the token, the grant and
        the approval id stay inside the channel, and none of them is
        placed in the returned plan's model-visible `parameters`.
        """

        # Same predicate the executor gates on. Imported from the
        # executor deliberately rather than reimplemented, so this seam
        # can never drift from the gate it is satisfying: if it disagreed,
        # we would prompt for operations that are not gated, or stay
        # silent for ones that are.
        from genesis_os.action_executor import (
            _operation_requires_authorization,
        )

        if not _operation_requires_authorization(
            plan.operation,
            getattr(plan, "capability_id", None),
            plan.parameters,
        ):
            # Tier 2. Not gated, so do not interrupt the human for it.
            return plan, None

        from genesis_os.action_plan import attach_authorization
        from genesis_os.approval_channel import (
            ApprovalChannel,
            build_request,
        )

        arguments = dict(plan.parameters or {})
        # Item 20A (S14): the prompt shows the human `target : ...`
        # (plan_target) but the approval hash was computed over
        # `arguments` alone, so a plan whose parameters do not carry the
        # path produced a grant bound to EMPTY arguments while the human
        # was shown the target -- displayed and approved were two
        # different things, and such a grant validated for any other
        # target too. Bind the target into the hashed arguments so what
        # is displayed, what is approved and what the executor
        # dispatches are one set.
        if plan.target is not None and str(plan.target).strip():
            arguments.setdefault("target", plan.target)

        try:
            request = build_request(
                plan.operation,
                arguments,
                plan_target=plan.target,
            )
        except Exception as error:
            print(
                "[Genesis OS] Could not prepare the approval "
                f"request: {error}"
            )
            return None, (
                "Genesis could not prepare a safe approval request for "
                "that action, so it was not performed."
            )

        # Reads the REPL's real stdin. With no TTY this denies by
        # default (approval_channel property 4), so a batch or piped run
        # can never approve anything.
        channel = ApprovalChannel(
            stdin=sys.stdin,
            stdout=sys.stdout,
        )

        decision = channel.request_approval(request)

        if not decision.get("approved"):
            note = decision.get("note") or "no decision recorded"
            print(
                "[Genesis OS] Not approved: " + str(note)
            )
            return None, (
                "Not performed: the approval was not granted "
                f"({note})."
            )

        try:
            grant = channel.mint_grant(request)
        except Exception as error:
            print(
                "[Genesis OS] Could not issue the approval grant: "
                f"{error}"
            )
            return None, (
                "Not performed: the approval could not be turned into a "
                "valid authorization grant."
            )

        # The grant rides the plan's trusted channel, never
        # plan.parameters, and `arguments` is the exact dict that was
        # hashed into the request the human saw.
        authorized_plan = attach_authorization(
            plan,
            grant,
            arguments=arguments,
        )

        return authorized_plan, None

    # =====================================================
    # LEVEL 3 — OS EXECUTION
    # =====================================================

    def run_level3(
        self,
        text,
        classification
    ):
        """
    Execute a Level 3 operating-system request.

    Level 3.3 architecture:

        Decision
            ↓
        ActionPlan
            ↓
        ActionExecutor
            ↓
        OSManager
            ↓
        ApplicationManager
            ↓
        Windows
            ↓
        Verification
            ↓
        ActionResult

    Level 3.17 adds compound-task routing:

        Decision
            ↓
        CompoundTaskRouter       (this method)
            ↓
        UniversalDesktopWorkflowEngine (multi-step path)
            ↓
        ActionExecutor (per step)
            ↓
        OSManager
            ↓
        ...

    Single-step L3 requests remain on the original
    ActionExecutor.execute() path; the compound path is
    purely additive and only fires when the request
    genuinely decomposes into 2+ executable Level-3 steps.
    """

        print()

        print(
            "[Genesis OS] "
            "Level 3 operating-system request detected."
        )

    # =========================================================
    # COMPOUND TASK ROUTING (Level 3.17)
    # =========================================================
    #
    # If the request is a multi-step L3 compound (e.g.
    # "open chrome, go to github, and search for langchain"),
    # build a WorkflowPlan and dispatch it through the
    # UniversalDesktopWorkflowEngine so EVERY step is
    # independently planned, executed, observed, verified and
    # recoverable. The single-step path below is preserved for
    # genuine single-action requests and is identical in
    # behaviour to the pre-3.17 path.

        try:
            outcome = (
                self.compound_task_router.route(text)
            )
        except Exception as exc:
            outcome = None
            print(
                f"[Genesis OS] Compound router "
                f"unavailable: {exc}"
            )

        if outcome is not None and outcome.plan is not None:
            print(
                "[Genesis OS] "
                f"Compound task detected "
                f"({outcome.signal.step_count} steps, "
                f"reason={outcome.signal.reason}). "
                "Dispatching through the workflow engine."
            )
            result = self.run_level3_workflow(outcome.plan)
            if result is None:
                # Engine unavailable; fall through to single-step.
                pass
            else:
                # Surface the per-step evidence honestly.
                return result

        classification = self._resolve_level3_capability(
            classification
        )
        if classification is None:
            return (
                "Genesis could not resolve that request to an "
                "available registered capability."
            )

    # =========================================================
    # BUILD ACTION PLAN
    # =========================================================

        try:

            plan = ActionPlan.from_decision(
                classification
            )

        except Exception as error:

            print(
                "[Genesis OS] "
                f"Action plan rejected: {error}"
            )

            return (
                "Genesis could not safely prepare "
                "that operating-system action."
            )

    # =========================================================
    # RESOLVE SEMANTIC TARGET
    # =========================================================
    #
    # A natural-language target such as "downloads" or
    # "my IELTS essay" must become the real Windows folder or
    # file BEFORE execution. Execution never guesses.

        plan = (
            self._resolve_semantic_target(
                plan
            )
        )
        if plan is None:
            return "Genesis could not resolve a safe filesystem target."

    # =========================================================
    # HUMAN APPROVAL (Directive 9A)
    # =========================================================
    #
    # Last point before execution, and the only one where the plan
    # object actually reaches the executor. Tier 2 plans pass through
    # untouched; a gated plan is offered to the human channel and comes
    # back carrying a real grant, or does not come back at all.

        plan, denial = (
            self._authorize_plan_for_execution(plan)
        )

        if plan is None:
            return denial

    # =========================================================
    # EXPLAIN PLAN
    # =========================================================

        print(
            "[Genesis OS] "
            f"Operation: {plan.operation}"
        )

        print(
            "[Genesis OS] "
            f"Target: {plan.target}"
        )

        print(
            "[Genesis OS] "
            f"Confidence: {plan.confidence:.2f}"
        )

        print(
            "[Genesis OS] "
            "Execution plan created."
        )

    # =========================================================
    # EXECUTE
    # =========================================================

        try:

            result = self.genesis_runtime.execute_audited(
                goal=text,
                operation=plan.operation,
                executor=self.action_executor,
                plan=plan,
            )

        except Exception as error:

            print(
                "[Genesis OS] "
                f"Execution gateway failure: {error}"
            )

            return (
                "Genesis encountered an unexpected "
                "problem while performing that "
                "operating-system action."
            )

    # =========================================================
    # RESULT INFORMATION
    # =========================================================

        print(
            "[Genesis OS] "
            f"Execution status: {result.status}"
        )

        print(
            "[Genesis OS] "
            f"Executed: {result.executed}"
        )

        print(
            "[Genesis OS] "
            f"Verified: {result.verified}"
        )

    # =========================================================
    # SESSION STATE UPDATE
    # =========================================================

        self._update_session_from_result(plan, result)

    # =========================================================
    # ENTITY HISTORY
    # =========================================================

        self.entity_history.record_from_result(
            plan.operation,
            plan.target or "",
            result.to_dict() if hasattr(result, "to_dict") else {},
            source_level=3,
        )
        if result.success and plan.target and str(plan.target).strip():
            target_path = Path(str(plan.target))
            if plan.operation.startswith("folder."):
                self.conversation_context.update("folder", str(target_path), target_path.name)
            elif target_path.is_file():
                self.conversation_context.update("file", str(target_path), target_path.name)

    # =========================================================
    # SUCCESS
    # =========================================================

        if result.success:

            print(
                "[Genesis OS] "
                "Operation completed successfully."
            )

        if result.verified:

            print(
                "[Genesis OS] "
                "Result verified."
            )

        elif result.already_in_desired_state:

            print(
                "[Genesis OS] "
                "Target was already in the "
                "requested state."
            )

            return result.user_message()

    # =========================================================
    # FAILURE
    # =========================================================

        else:

            # result.verified is False AND the target was not
            # already in the desired state. The earlier
            # branches (line 1347 "Operation completed
            # successfully." / line 1354 "Result verified.")
            # were silent for this case, so this is the only
            # place the negative observation can be surfaced.
            # Previously this print was UNCONDITIONAL, which
            # meant it fired for the verified case too and
            # contradicted the "Result verified." line for the
            # same single operation.
            print(
                "[Genesis OS] "
                "Operation was NOT verified successfully."
            )

            if result.error:

                print(
                    "[Genesis OS] "
                    f"Error: {result.error}"
                )

            return result.user_message()

    # =========================================================
    # VERIFIED SUCCESS FALLTHROUGH
    # =========================================================
    #
    # When the operation was verified (or already in desired
    # state), the verified/already branches above are responsible
    # for the return path. If neither of the negative branches
    # was taken, fall through and return the user-facing message
    # so we never accidentally re-enter this method's failure
    # print after a verified success.

        return result.user_message()

    # =========================================================
    # SESSION STATE UPDATE HELPERS
    # =========================================================

    def _update_session_from_result(self, plan, result):
        """
        Update session state after a Level 3 execution.
        Every state transition is observable through SessionState.
        """

        op = plan.operation
        target = plan.target or ""

        try:
            if op == "application.open" and result.success:
                self.session_state.update_application(
                    target, is_focused=True
                )

            elif op == "application.close" and result.success:
                self.session_state.mark_application_closed(target)

            elif op in ("folder.open", "folder.create") and result.success:
                self.session_state.set_current_folder(target)

            elif op in ("file.open", "file.read", "file.create") and result.success:
                self.session_state.set_active_document(target)

            elif op == "browser.open_url" and result.success:
                self.session_state.update_browser(
                    "browser", url=target
                )

            elif op == "browser.search" and result.success:
                params = plan.parameters or {}
                self.session_state.update_browser(
                    "browser",
                    search_query=params.get("query", target),
                    search_engine=params.get("engine", "google"),
                )

            elif op == "clipboard.copy" and result.success:
                params = plan.parameters or {}
                self.session_state.set_clipboard(
                    params.get("text", target)
                )

        except Exception as exc:
            print(
                f"[Genesis OS] Session state update "
                f"skipped: {exc}"
            )

    def _record_level2_entities(self, classification, response):
        """
        After a Level 2 agent completes, record any entities
        it produced or referenced into the entity history.

        This preserves provenance: a file created by the Coding
        Agent is tracked so a later "open it" can resolve to it.
        """

        agent_name = classification.get("agent", "")
        agents = classification.get("agents", [])

        if not agent_name and agents:
            agent_name = agents[0] if isinstance(agents, list) else str(agents)

        response_text = ""
        if isinstance(response, str):
            response_text = response
        elif isinstance(response, dict):
            response_text = str(response.get("result", response))

        if not response_text:
            return

        lower = response_text.lower()

        import re as _re

        file_patterns = [
            r"(?:created?|saved?|wrote?|generated?|written? to|output)\s+(?:file\s+)?(?:at\s+)?([^\s,;]+(?:\.\w+))",
            r"(?:file|document|script)\s+(?:saved?|created?|written?)\s+(?:at\s+)?([^\s,;]+(?:\.\w+))",
        ]

        for pattern in file_patterns:
            match = _re.search(pattern, lower)
            if match:
                entity_id = match.group(1)
                self.entity_history.record(
                    EntityType.FILE,
                    entity_id,
                    EntityAction.CREATED,
                    source_level=2,
                    source_agent=agent_name,
                )
                self.session_state.add_recent_file(entity_id)
                if Path(entity_id).is_file():
                    self.conversation_context.update("file", entity_id, Path(entity_id).name)
                break

    def _resolve_session_reference(self, text):
        """
        Attempt to resolve vague references in the user's text
        using session state and entity history.

        Returns the text with references resolved, or the original
        text if resolution is not possible.
        """

        lower = text.lower().strip()

        pronouns = ("it", "that", "this", "them", "those")

        words = lower.split()

        if not words:
            return text

        for pronoun in pronouns:
            if pronoun in words:
                resolved = self.entity_history.resolve_pronoun(
                    pronoun
                )
                if resolved:
                    text = text.replace(pronoun, resolved, 1)
                    print(
                        f"[Genesis] Resolved '{pronoun}' "
                        f"-> '{resolved}'"
                    )
                    break

        return text


    # =====================================================
    # LEVEL 3.8 — UNIVERSAL DESKTOP WORKFLOW
    # =====================================================

    def run_level3_workflow(self, workflow, *, context=None, replanner=None, max_replans=0):
        """Execute a pre-built objective workflow through the Level 3.8 engine.

        Objective understanding/decomposition is intentionally kept outside the
        execution engine. The supplied WorkflowPlan is validated, safety-gated,
        executed sequentially and verified before success is reported.
        """
        return self.universal_workflow.execute(
            workflow,
            context=context,
            replanner=replanner,
            max_replans=max_replans,
        )

    # =====================================================
    # LEVEL 2 EXECUTION
    # =====================================================

    def run_level2(
        self,
        text,
        classification
    ):

        print(
            "\n[Genesis Router] "
            "Level 2 request detected."
        )

        mode = classification.get(
            "mode",
            "single_agent"
        )

        # =================================================
        # SINGLE AGENT
        # =================================================

        if mode == "single_agent":

            agent_name = (
                classification.get(
                    "agent"
                )
            )

            if not agent_name:

                agents = (
                    classification.get(
                        "agents",
                        []
                    )
                )

                if agents:

                    agent_name = (
                        agents[0]
                    )

            if not agent_name:

                print(
                    "[Genesis] "
                    "No specialized agent selected."
                )

                return (
                    "Genesis could not determine "
                    "the specialized agent for "
                    "this request."
                )

            print(
                "[Genesis Router] "
                "Single-agent workflow."
            )

            print(
                "[Genesis Router] "
                f"Selected: {agent_name}"
            )

            task = {
                "task": text,
                "agent": agent_name
            }

            print(
                "[Genesis] "
                "Executing specialized agent..."
            )

            result = (
                self.executor.execute(
                    [task]
                )
            )

            return (
                self._extract_response(
                    result
                )
            )

        # =================================================
        # MULTI AGENT
        # =================================================

        if mode == "multi_agent":

            return self.run_multi_agent(
                text,
                classification
            )

        # =================================================
        # UNKNOWN MODE
        # =================================================

        print(
            "[Genesis] "
            "Unknown Level 2 workflow mode."
        )

        print(
            "[Genesis] "
            "Falling back to Level 1 Brain."
        )

        return self.brain.think(
            text
        )

    # =====================================================
    # MULTI-AGENT WORKFLOW
    # =====================================================

    def run_multi_agent(
        self,
        text,
        classification
    ):

        print()

        print(
            "=" * 46
        )

        print(
            " GENESIS INTELLIGENT "
            "MULTI-AGENT WORKFLOW"
        )

        print(
            "=" * 46
        )

        agents = classification.get(
            "agents",
            []
        )

        # -------------------------------------------------
        # FALLBACK TO ORCHESTRATOR
        # -------------------------------------------------

        if not agents:

            print(
                "[Genesis] "
                "No agents explicitly selected."
            )

            print(
                "[Genesis] "
                "Orchestrator creating "
                "execution plan..."
            )

            plan = (
                self.orchestrator
                .create_intelligent_plan(
                    text
                )
            )

            tasks = (
                self.orchestrator
                .prepare_intelligent_tasks(
                    plan
                )
            )

        else:

            print(
                f"[Genesis] Selected "
                f"{len(agents)} specialized agents."
            )

            print()

            for index, agent in enumerate(
                agents,
                start=1
            ):

                print(
                    f"  {index}. {agent}"
                )

            # -------------------------------------------------
            # CREATE TASKS
            # -------------------------------------------------

            tasks = []

            for agent_name in agents:

                tasks.append(
                    {
                        "task": text,
                        "agent": agent_name
                    }
                )

        # -------------------------------------------------
        # NO TASKS
        # -------------------------------------------------

        if not tasks:

            print(
                "[Genesis] "
                "No executable workflow tasks."
            )

            return (
                "Genesis could not create "
                "an executable multi-agent workflow."
            )

        print()

        print(
            f"[Genesis] Prepared "
            f"{len(tasks)} agent task(s)."
        )

        # -------------------------------------------------
        # EXECUTE
        # -------------------------------------------------

        print()

        print(
            "[Genesis] "
            "Executing multi-agent workflow..."
        )

        results = (
            self.executor.execute(
                tasks
            )
        )

        print()

        print(
            "[Genesis] "
            "Multi-agent execution completed."
        )

        # -------------------------------------------------
        # SHARED CONTEXT
        # -------------------------------------------------

        context_results = (
            self.context.get_results()
        )

        print(
            "[Genesis] Shared context now contains "
            f"{len(context_results)} result(s)."
        )

        # -------------------------------------------------
        # VALIDATE & AGGREGATE RESULTS
        # -------------------------------------------------

        aggregated = self.aggregator.aggregate(results)

        # -------------------------------------------------
        # FINAL SYNTHESIS
        # -------------------------------------------------

        return (
            self.synthesize_multi_agent_results(
                text,
                aggregated["results"]
            )
        )

    # =====================================================
    # MULTI-AGENT SYNTHESIS
    # =====================================================

    def synthesize_multi_agent_results(
        self,
        user_request,
        results
    ):
        """
        Genesis acts as the final intelligence layer.

        Specialized agents perform specialized work.

        Genesis synthesizes their outputs into
        one coherent response.
        """

        print()

        print(
            "[Genesis] "
            "Synthesizing multi-agent results..."
        )

        if not results:

            return (
                "The multi-agent workflow completed "
                "without producing usable results."
            )

        # -------------------------------------------------
        # EXTRACT AGENT RESULTS
        # -------------------------------------------------

        result_blocks = []

        if isinstance(
            results,
            list
        ):

            for index, item in enumerate(
                results,
                start=1
            ):

                if not isinstance(
                    item,
                    dict
                ):

                    continue

                agent_name = item.get(
                    "agent",
                    "Unknown Agent"
                )

                raw_result = item.get(
                    "result"
                )

                response = (
                    self._response_from_result(
                        raw_result
                    )
                )

                if not response:

                    response = str(
                        raw_result
                    )

                result_blocks.append(
                    f"""
==============================
AGENT RESULT {index}
==============================

AGENT:
{agent_name}

RESULT:
{response}
"""
                )

        else:

            response = (
                self._response_from_result(
                    results
                )
            )

            if response:

                result_blocks.append(
                    f"""
==============================
AGENT RESULT
==============================

RESULT:
{response}
"""
                )

        if not result_blocks:

            return self._extract_response(
                results
            )

        combined_results = (
            "\n".join(
                result_blocks
            )
        )

        # -------------------------------------------------
        # FINAL SYNTHESIS PROMPT
        # -------------------------------------------------

        synthesis_prompt = f"""
You are Genesis OS, the final intelligence layer
of a unified AI operating system.

The user requested:

{user_request}

Several specialized Genesis agents worked on
the same task.

Their results are:

{combined_results}

Your responsibility is to synthesize their work
into ONE high-quality Genesis response.

IMPORTANT:

1. Combine complementary findings.
2. Remove unnecessary duplication.
3. Do not blindly copy every agent response.
4. Do not invent unsupported facts.
5. Distinguish facts, analysis, recommendations,
   and uncertainty when appropriate.
6. Preserve important disagreements or limitations.
7. If an agent failed or produced incomplete output,
   acknowledge that limitation when relevant.
8. The answer must feel like ONE intelligent
   Genesis response.
9. Make the result practical and useful.
10. Do not mention internal prompts, routing,
    implementation details, or hidden system logic
    unless the user explicitly asks.
11. Prefer a clear structure with useful headings
    when the task is complex.
12. Answer the user's actual request directly.

Return ONLY the final response.
"""

        try:

            final_response = (
                self.brain.think(
                    synthesis_prompt
                )
            )

            if final_response:

                print(
                    "[Genesis] "
                    "Final synthesis completed."
                )

                return final_response

        except Exception as error:

            print(
                f"[Genesis] "
                f"Synthesis failed: {error}"
            )

        # -------------------------------------------------
        # FALLBACK
        # -------------------------------------------------

        print(
            "[Genesis] "
            "Using multi-agent results directly."
        )

        return self._extract_response(
            results
        )

    # =====================================================
    # RESULT EXTRACTION
    # =====================================================

    def _extract_response(
        self,
        results
    ):

        if not results:

            return (
                "Genesis could not produce "
                "an agent result."
            )

        # -------------------------------------------------
        # LIST
        # -------------------------------------------------

        if isinstance(
            results,
            list
        ):

            responses = []

            for item in results:

                if not isinstance(
                    item,
                    dict
                ):

                    continue

                result = item.get(
                    "result"
                )

                response = (
                    self._response_from_result(
                        result
                    )
                )

                if response:

                    responses.append(
                        response
                    )

            if responses:

                return responses[-1]

            return (
                "The agent workflow completed, "
                "but no response was returned."
            )

        # -------------------------------------------------
        # SINGLE RESULT
        # -------------------------------------------------

        response = (
            self._response_from_result(
                results
            )
        )

        if response:

            return response

        return str(
            results
        )

    # =====================================================
    # RECURSIVE RESULT EXTRACTION
    # =====================================================

    @staticmethod
    def _response_from_result(
        result
    ):

        if isinstance(
            result,
            dict
        ):

            response = result.get(
                "response"
            )

            if response:

                return response

            nested = result.get(
                "result"
            )

            if nested is not None:

                return (
                    GenesisOS
                    ._response_from_result(
                        nested
                    )
                )

        elif isinstance(
            result,
            str
        ):

            if result.strip():

                return result

        return None

    # =====================================================
    # COMMANDS
    # =====================================================

    def command(
        self,
        text
    ):

        command = (
            text.lower().strip()
        )

        # -------------------------------------------------
        # HELP
        # -------------------------------------------------

        if command == "help":

            print(
                "\nGenesis commands:"
            )

            print(
                "  help       — show commands"
            )

            print(
                "  agents     — list Level 2 agents"
            )

            print(
                "  status     — show Genesis system status"
            )

            print(
                "  context    — show current agent context"
            )

            print(
                "  clear      — clear agent context"
            )

            print(
                "  history    — show conversation history"
            )

            print(
                "  os         — show Level 3 OS capabilities"
            )

            print(
                "  exit       — close Genesis"
            )

            return True

        # -------------------------------------------------
        # AGENTS
        # -------------------------------------------------

        if command == "agents":

            print(
                "\nLevel 2 Agents:"
            )

            for agent in (
                self.registry.get_all_agents()
            ):

                print(
                    f"  ✓ {agent.name} "
                    f"— {agent.description}"
                )

            return True

        # -------------------------------------------------
        # STATUS
        # -------------------------------------------------

        if command == "status":

            status = (
                self.registry.status()
            )

            os_status = (
                self.os_manager.status()
            )

            print(
                "\nGenesis Status"
            )

            print(
                "  Level 1: ONLINE"
            )

            print(
                "  Level 2: ONLINE"
            )

            print(
                "  Level 3: "
                f"{'ONLINE' if os_status.get('level') == 3 else 'OFFLINE'}"
            )

            print(
                "  Application Intelligence: "
                f"{'ONLINE' if os_status.get('application_intelligence') else 'OFFLINE'}"
            )

            print(
                "  Workflow Decision: ONLINE"
            )

            print(
                "  Single-Agent Workflows: ONLINE"
            )

            print(
                "  Multi-Agent Workflows: ONLINE"
            )

            print(
                "  Agents: "
                f"{status['agent_count']}"
            )

            print(
                "  Shared context results: "
                f"{len(self.context.get_results())}"
            )

            return True

        # -------------------------------------------------
        # OS
        # -------------------------------------------------

        if command == "os":

            status = (
                self.os_manager.status()
            )

            print(
                "\nGenesis OS — Level 3"
            )

            print(
                "  OS Core ....................... "
                f"{'ONLINE' if status.get('level') == 3 else 'OFFLINE'}"
            )

            print(
                "  Application Intelligence ...... "
                f"{'ONLINE' if status.get('application_intelligence') else 'NOT IMPLEMENTED'}"
            )

            print(
                "  File Intelligence ............. "
                f"{'ONLINE' if status.get('file_intelligence') else 'NOT IMPLEMENTED'}"
            )

            print(
                "  Folder Intelligence ........... "
                f"{'ONLINE' if status.get('folder_intelligence') else 'NOT IMPLEMENTED'}"
            )

            print(
                "  Process Intelligence .......... "
                f"{'ONLINE' if status.get('process_intelligence') else 'NOT IMPLEMENTED'}"
            )

            print(
                "  System Intelligence ........... "
                f"{'ONLINE' if status.get('system_intelligence') else 'NOT IMPLEMENTED'}"
            )

            print(
                "  Document Intelligence ......... "
                f"{'ONLINE' if status.get('document_intelligence') else 'NOT IMPLEMENTED'}"
            )

            return True

        # -------------------------------------------------
        # CONTEXT
        # -------------------------------------------------

        if command == "context":

            results = (
                self.context.get_results()
            )

            print(
                f"\nShared Context: "
                f"{len(results)} result(s)"
            )

            for index, item in enumerate(
                results,
                start=1
            ):

                if isinstance(
                    item,
                    dict
                ):

                    print(
                        f"  {index}. "
                        f"{item.get('agent', 'Unknown')}"
                    )

                else:

                    print(
                        f"  {index}. "
                        f"{item}"
                    )

            return True

        # -------------------------------------------------
        # CLEAR
        # -------------------------------------------------

        if command == "clear":

            self.context.clear()

            print(
                "[Genesis] "
                "Agent context cleared."
            )

            return True

        # -------------------------------------------------
        # HISTORY
        # -------------------------------------------------

        if command == "history":

            print(
                "\n----- Conversation History -----"
            )

            for chat in (
                self.conversation.get_history()
            ):

                print(
                    f"{chat['role']}: "
                    f"{chat['message']}"
                )

            print(
                "-------------------------------"
            )

            return True

        # -------------------------------------------------
        # UNKNOWN COMMAND
        # -------------------------------------------------

        return False

    def plan_level3_objective(
        self,
        text,
        *,
        workflow_id="",
        metadata=None,
    ):
        """
    Understand and decompose a natural-language desktop
    objective into a validated WorkflowPlan.

    This method NEVER executes the workflow.

    Pipeline:

        text
          ↓
        ObjectiveUnderstanding
          ↓
        WorkflowDecomposer
          ↓
        WorkflowPlan
        """

        understanding = (
            self.objective_understanding.understand(
                text
            )
        )

        decomposition = (
            self.workflow_decomposer.decompose(
                understanding,
                workflow_id=workflow_id,
                metadata=metadata,
            )
        )

        return {
            "understanding": understanding,
            "decomposition": decomposition,
        }

    # =====================================================
    # LEVEL 3 — UNIFIED REQUEST HANDLER
    # =====================================================

    def _handle_level3_request(
        self,
        text,
        classification,
    ):
        """
        Route a Level 3 operating-system request.

        Multi-step objectives are understood, decomposed,
        resolved and executed as verified workflows.

        Single actions keep the established single-action
        execution path.
        """

        # Record the durable parts of this turn so the next
        # conversational continuation can bind to them.
        self.session_context_binder.record_decision(
            classification
        )

        response = (
            self._try_multi_step_workflow(text)
        )

        if response is not None:
            return response

        return self.run_level3(
            text,
            classification,
        )

    def _try_multi_step_workflow(self, text):
        """
        Attempt to understand and execute a multi-step desktop
        objective. Returns a natural-language result string, or
        None when the objective should be handled by the
        single-action path instead.
        """

        try:
            planned = (
                self.plan_level3_objective(
                    text,
                    metadata={"source": "runtime"},
                )
            )

        except Exception as error:

            print(
                "[Genesis OS] "
                "Objective planning unavailable: "
                f"{error}"
            )

            return None

        understanding = planned["understanding"]
        decomposition = planned["decomposition"]

        # -----------------------------------------------------
        # MIXED OBJECTIVES — CROSS-LEVEL ORCHESTRATION
        #
        # "open vs code and write a python calculator"
        #
        # Level 3 executes the desktop actions; Level 2 agents
        # (or the core brain) handle the intelligence parts.
        # All levels work TOGETHER on one objective.
        # -----------------------------------------------------

        if len(understanding.steps) > 1 and not decomposition.executable:
            mixed = self._handle_mixed_objective(understanding)

            if mixed is not None:
                return mixed

        if not decomposition.executable:
            # A mixed objective must never silently execute
            # only its understood part.
            if any(
                step.executable_intent
                for step in understanding.steps
            ):
                blocked = [
                    step.text
                    for step in understanding.steps
                    if not step.executable_intent
                ]

                return (
                    "Genesis understood this as a "
                    "multi-step objective, but could not "
                    "safely execute every step: "
                    + "; ".join(blocked)
                    + ". Please complete those parts "
                    "separately."
                )

            return None

        workflow = decomposition.workflow

        step_label = "step" if len(workflow.steps) == 1 else "steps"
        print(
            "[Genesis OS] "
            f"Objective decomposed into "
            f"{len(workflow.steps)} {step_label}."
        )

        updated_workflow, resolutions = (
            self.workflow_target_resolver.resolve_workflow(
                workflow
            )
        )

        if updated_workflow is None:

            unclear = [
                resolution.clarification_reason
                or "The target could not be resolved."
                for resolution in resolutions.values()
                if not resolution.successful
            ]

            return (
                "Genesis could not resolve a target "
                "needed for this workflow: "
                + " ".join(unclear)
            )

        result = self.run_level3_workflow(
            updated_workflow,
            context={"objective": text},
        )

        return self._format_workflow_result(result)

    # =====================================================
    # LEVEL 3 — AI INTENT RESOLUTION FOR UNMATCHED REQUESTS
    # =====================================================

    _AFFIRMATIVE_RE = None  # compiled lazily below
    _NEGATIVE_RE = None

    def _handle_unmatched_request(self, text):
        """
        Called when deterministic routing resolved the request as
        ordinary conversation.

        This is where a universal AI OS earns its name: an AI
        resolver maps the request onto the registered capability
        catalog, and Genesis proposes the action for explicit
        confirmation instead of either guessing or giving up.
        """

        # -----------------------------------------------------
        # 1. PENDING ACTION — CONFIRMATION HANDSHAKE
        # -----------------------------------------------------

        if self._pending_llm_action is not None:
            normalized = str(text or "").strip().lower()

            affirmative = re.fullmatch(
                r"(?:yes|y|yeah|yep|sure|confirm(?:ed)?|do it|go ahead|"
                r"proceed|ok(?:ay)?|please do|do that)\b[.!]?",
                normalized,
            )
            negative = re.search(
                r"\b(no|n|cancel|stop|don'?t|do not|nevermind|"
                r"never mind|forget it)\b",
                normalized,
            )

            if affirmative:
                return self._execute_pending_action()
            if negative and len(normalized) <= 30:
                self._pending_llm_action = None
                return "Understood. I will not perform that action."

            # A new request replaces the pending proposal.
            self._pending_llm_action = None

        # -----------------------------------------------------
        # 2. AI INTENT RESOLUTION
        # -----------------------------------------------------

        candidate = None

        try:
            if LLMIntentResolver.looks_actionable(text):
                print(
                    "[Genesis OS] "
                    "Resolving with AI intent layer..."
                )

                candidate = (
                    self.llm_intent_resolver.resolve(
                        text
                    )
                )
        except Exception as error:
            print(
                "[Genesis OS] "
                f"AI intent resolution unavailable: {error}"
            )

        if candidate is None:
            return None

        # -----------------------------------------------------
        # 3. PROPOSE FOR EXPLICIT CONFIRMATION
        # -----------------------------------------------------

        operation = candidate.get("operation")

        description = self._describe_operation(
            operation,
            candidate.get("target"),
            candidate.get("parameters") or {},
        )

        from genesis_os.action_plan import (
            ActionPlan as _ActionPlan,
        )

        try:
            plan = _ActionPlan.from_decision(candidate)
        except Exception:
            return None

        self._pending_llm_action = {
            "plan": plan,
            "decision": dict(candidate),
            "description": description,
        }

        return (
            f"I understood that as: {description}.\n"
            "Shall I proceed? (yes / no)"
        )

    def _execute_pending_action(self):
        pending = self._pending_llm_action
        self._pending_llm_action = None

        if not pending:
            return None

        decision = pending["decision"]

        # The user explicitly confirmed this exact action; the
        # confidence now reflects a confirmed human decision.
        confirmed_decision = dict(decision)
        confirmed_decision["confidence"] = 0.99
        confirmed_decision["source"] = "LLMIntentResolver+user_confirmed"

        parameters = dict(confirmed_decision.get("parameters") or {})

        # REWRITTEN 2026-10-08 (F5). This used to read the capability's
        # `requires_confirmation` / `confirmation_required` metadata and inject
        # `parameters["confirmed"] = True`, then unconditionally print
        # "Confirmed action approved by user."
        #
        # That was self-approval by metadata: the caller manufactured the flag
        # that satisfied the old confirmation gate, and the message claimed a
        # human had approved something regardless of what was actually about to
        # run. `confirmed` is no longer an authority anywhere in the executor,
        # so the injection is removed rather than left as decoration.
        #
        # The user's "yes" is still recorded -- as `source`, above, which the
        # decision layer already distinguishes. It is NOT sufficient to authorise
        # a Tier 1 operation: that needs a genuine AuthorizationGrant.
        #
        # CORRECTED 2026-10-14 (audit C-02). The original comment here said
        # "no approval flow issues one yet", and the printed message said "no
        # approval channel exists yet". Both were FALSE: the channel exists
        # (genesis_os/approval_channel.py, approval_store.py,
        # authorization_grant.py) and action_executor.py:783 consumes grants
        # it issues. The runtime itself says so - the real refusal message is
        # "This operation is irreversible or outward-facing and requires a
        # human-approval grant."
        #
        # What remains true is narrower and is what the message now says:
        # THIS path does not issue a grant. Recording a confirmation is not
        # authorisation, and only the human-approval channel can mint one.

        confirmed_decision["parameters"] = parameters

        print(
            "[Genesis OS] "
            "Recorded your confirmation. It is recorded as the decision "
            "source, NOT as authorisation: saying 'yes' here does not "
            "issue the approval grant that a destructive or "
            "outward-facing operation needs. That grant can only come "
            "from the human-approval channel "
            "(genesis_os.approval_channel), and this path is not it."
        )

        return self._handle_level3_request(
            decision.get("task", ""),
            confirmed_decision,
        )

    @staticmethod
    def _describe_operation(operation, target, parameters):
        """
        Human-friendly phrasing of what Genesis proposes to do.

        The text shown to the user MUST NOT contain the raw
        capability id (e.g. ``cleanup.recycle_bin_query``) —
        it must read like a normal sentence a person could
        understand and consent to. The source of truth for
        the description is the canonical descriptor in
        ``CapabilityRegistry``, which already requires a
        plain-language ``description`` field per the
        Capability Contract.

        Resolution order:

            1. Explicit override in the ``_FRIENDLY_OVERRIDES``
               table below — used only for operations whose
               canonical description is awkward as a
               confirmation prompt and where a tight,
               imperative phrasing is clearer.
            2. The capability's ``description`` field from
               ``CapabilityRegistry``. Trailing technical
               noise ("Read-only.", "Requires confirmation.")
               is stripped before the text is shown.
            3. A friendly fallback derived from the operation
               id, with the raw id NEVER appearing in the
               returned string. If even this fallback has to
               be used, the missing description is recorded
               in the log so it can be fixed in the registry.

        The raw operation id, target, and parameters are
        always recorded via ``print`` at debug level so
        future debugging can still correlate the user's
        confirmation prompt with the exact capability
        that would be invoked.
        """

        from genesis_os.capability_registry import (
            CapabilityRegistry,
        )

        if not operation:
            return "perform an OS action"

        if target is None:
            target = ""

        parameters = parameters or {}

        # -----------------------------------------------------
        # 1. Explicit overrides (tight imperative phrasing)
        # -----------------------------------------------------

        friendly_overrides = {
            "screen.capture": "take a screenshot",
            "volume.set": "set the volume",
            "volume.mute_toggle": "change the mute state",
            "display.brightness_set": "adjust screen brightness",
            "hardware.battery": "check the battery",
            "hardware.stats": "check system performance",
            "clipboard.copy": "copy text to the clipboard",
            "workstation.lock": "lock your workstation",
            "media.play_pause": "toggle media playback",
        }

        base = friendly_overrides.get(operation)

        if base is None and CapabilityRegistry.exists(
            operation
        ):
            capability = CapabilityRegistry.get(operation)
            descriptor_description = (
                capability.description
                if capability is not None
                else ""
            )

            cleaned = _strip_descriptor_noise(
                descriptor_description
            )

            if cleaned:
                base = cleaned
            else:
                print(
                    "[Genesis OS] Confirmation prompt "
                    "fallback used: capability "
                    f"'{operation}' has no usable "
                    "plain-language description in its "
                    "CapabilityRegistry descriptor."
                )
                base = _friendly_from_operation_id(operation)

        if base is None:
            print(
                "[Genesis OS] Confirmation prompt "
                "fallback used: operation "
                f"'{operation}' is not registered in "
                "CapabilityRegistry."
            )
            base = _friendly_from_operation_id(operation)

        detail = ""

        if operation == "volume.set":
            percent = parameters.get("percent")
            if percent is not None:
                detail = f" to {percent}%"
        elif operation == "display.brightness_set":
            percent = parameters.get("percent")
            if percent is not None:
                detail = f" to {percent}%"
        elif operation in ("application.open", "application.close"):
            if target:
                detail = f" {target}"

        user_facing_text = f"{base}{detail}".strip()

        # Debug log: keep the raw operation id available
        # for future debugging, but never in the user-facing
        # confirmation prompt.
        print(
            "[Genesis OS] Confirm action "
            f"operation={operation!r} "
            f"target={target!r} "
            f"user_text={user_facing_text!r}"
        )

        return user_facing_text

    # =====================================================
    # LEVEL 3+2+1 — CROSS-LEVEL ORCHESTRATION
    # =====================================================

    def _handle_mixed_objective(self, understanding):
        """
        Execute an objective that combines desktop actions with
        intelligence work:

            "open vs code and write a python calculator"
                Level 3: open VS Code (verified)
                Level 2: coding agent writes the calculator

        Returns a combined natural-language result, or None when
        the objective does not actually mix levels.
        """

        l3_steps = [
            step for step in understanding.steps
            if step.executable_intent
        ]

        other_steps = [
            step for step in understanding.steps
            if not step.executable_intent
        ]

        if not l3_steps or not other_steps:
            return None

        print(
            "[Genesis] Cross-level objective detected: "
            f"{len(l3_steps)} OS step(s) + "
            f"{len(other_steps)} intelligence step(s)."
        )

        try:
            result = self.genesis_runtime.execute_mixed_audited(
                understanding.objective,
                self.unified_executor,
            )
        except Exception as error:
            return (
                "The mixed objective could not be completed: "
                f"{error}"
            )

        if result.success and result.final_verified:
            return result.message
        return self._format_workflow_result(result)

    @staticmethod
    def _format_workflow_result(workflow_result):

        status = getattr(
            workflow_result,
            "status",
            "",
        )

        message = getattr(
            workflow_result,
            "message",
            "",
        ) or ""

        if getattr(workflow_result, "success", False):
            return message or (
                "The objective was completed and "
                "verified."
            )

        if status == "confirmation_required":
            return (
                message
                or "This action requires your explicit "
                "confirmation before Genesis can "
                "execute it."
            )

        error = getattr(
            workflow_result,
            "error",
            None,
        )

        base = (
            message
            or "The objective could not be completed."
        )

        if status == "verification_failed":
            base += (
                " Genesis executed the steps but could "
                "not verify the final state, so it is "
                "not reporting success."
            )

        if error and error not in base:
            base += f" ({error})"

        return base

    # =====================================================
    # MAIN RUNTIME LOOP
    # =====================================================

    def run(self):

        self.show_startup()

        while self.running:

            try:

                user_input = input(
                    "\nYou: "
                )

            except (
                EOFError,
                KeyboardInterrupt
            ):

                print(
                    "\n\nGenesis: "
                    "Goodbye! See you soon."
                )

                break

            # -------------------------------------------------
            # PREPARE MESSAGE
            # -------------------------------------------------

            prepared_message = (
                self.conversation
                .prepare_message(
                    user_input
                )
            )

            if prepared_message is None:

                print(
                    "\nGenesis: "
                    "Please type a message."
                )

                continue

            # -------------------------------------------------
            # EXIT
            # -------------------------------------------------

            if (
                prepared_message
                .lower()
                .strip()
                == "exit"
            ):

                print(
                    "\nGenesis: "
                    "Goodbye! See you soon."
                )

                break

            # -------------------------------------------------
            # SYSTEM COMMAND
            # -------------------------------------------------

            if self.command(
                prepared_message
            ):

                continue

            # -------------------------------------------------
            # SAVE USER MESSAGE
            # -------------------------------------------------

            self.conversation.add_message(
                "user",
                prepared_message
            )

            # -------------------------------------------------
            # LONG-TERM MEMORY COMMANDS
            #
            # "what do you know about me" · "forget my name"
            # "remember that ..." — answered directly from the
            # persistent memory store.
            # -------------------------------------------------

            memory_command_response = None

            try:
                memory_command_response = (
                    self.long_term_memory.handle_command(
                        prepared_message
                    )
                )

            except Exception as memory_error:

                print(
                    "[Memory] Command error: "
                    f"{memory_error}"
                )

            if memory_command_response is not None:

                print(
                    "[Memory] Handled as a memory command."
                )

                print(
                    f"\nGenesis: "
                    f"{memory_command_response}"
                )

                self.conversation.add_message(
                    "assistant",
                    memory_command_response
                )

                continue

            # -------------------------------------------------
            # SESSION REFERENCE RESOLUTION
            #
            # "Open it." → "Open C:\Users\...\results.xlsx"
            #
            # Resolves pronouns and vague references using
            # entity history before routing.
            # -------------------------------------------------

            routing_text = self._resolve_session_reference(
                prepared_message
            )

            # -------------------------------------------------
            # WORKFLOW DECISION
            #
            # MULTILINGUAL UNDERSTANDING: any language in,
            # English OS command out. The original message is
            # preserved for the response; routing uses the
            # understood command.
            # -------------------------------------------------

            try:
                if self.language_normalizer.needs_translation(
                    prepared_message
                ):
                    translated = (
                        self.language_normalizer.to_english_command(
                            prepared_message
                        )
                    )

                    if translated:
                        print(
                            "[Genesis] Understood: "
                            f"'{translated['english']}'"
                        )

                        routing_text = translated["english"]

            except Exception as translation_error:

                print(
                    "[Genesis] "
                    f"Translation unavailable: {translation_error}"
                )

            classification = (
                self.classify(
                    routing_text
                )
            )

            # -------------------------------------------------
            # SESSION CONTEXT CONTINUATION
            #
            # "Open Chrome." → "Now search YouTube for Python."
            #
            # A follow-up that begins with conversational glue
            # ("now", "then", ...) is re-evaluated against the
            # previous Level 3 session context.
            # -------------------------------------------------

            if (
                classification.get(
                    "level"
                )
                != 3
            ):

                rebound = (
                    self.session_context_binder.try_rebind(
                        routing_text
                    )
                )

                if rebound is not None:

                    print(
                        "[Genesis Decision] "
                        "Continuation of previous "
                        "operating-system request."
                    )

                    classification = rebound

            print(
                f"[Genesis Router] "
                f"Level {classification['level']} "
                f"→ {classification['mode']}"
            )

            if classification.get(
                "reason"
            ):

                print(
                    "[Genesis Decision] "
                    f"{classification['reason']}"
                )

            # -------------------------------------------------
            # LEVEL 2 AGENT DISPLAY
            # -------------------------------------------------

            if (
                classification["mode"]
                == "single_agent"
            ):

                selected_agent = (
                    classification.get(
                        "agent"
                    )
                )

                if selected_agent:

                    print(
                        "[Genesis Decision] "
                        f"Selected: {selected_agent}"
                    )

            elif (
                classification["mode"]
                == "multi_agent"
            ):

                selected_agents = (
                    classification.get(
                        "agents",
                        []
                    )
                )

                print(
                    "[Genesis Decision] "
                    "Multi-agent workflow selected."
                )

                for agent in selected_agents:

                    print(
                        f"  → {agent}"
                    )

            # -------------------------------------------------
            # LEVEL 3 DISPLAY
            # -------------------------------------------------

            elif (
                classification["level"]
                == 3
            ):

                print(
                    "[Genesis Decision] "
                    "Operating-system capability selected."
                )

                if classification.get(
                    "intent"
                ):

                    print(
                        "[Genesis OS] "
                        f"Intent: {classification['intent']}"
                    )

                if classification.get(
                    "application"
                ):

                    print(
                        "[Genesis OS] "
                        f"Target: {classification['application']}"
                    )

            # -------------------------------------------------
            # EXECUTION
            # -------------------------------------------------

            try:

                # -------------------------------------------------
                # LEVEL 3
                # -------------------------------------------------

                if (
                    classification["level"]
                    == 3
                ):

                    response = (
                        self._handle_level3_request(
                            routing_text,
                            classification
                        )
                    )

                # -------------------------------------------------
                # LEVEL 2
                # -------------------------------------------------

                elif (
                    classification["level"]
                    == 2
                ):

                    # -------------------------------------
                    # LONG-TERM MEMORY → AGENT CONTEXT
                    #
                    # Agents answer with knowledge of the user.
                    # -------------------------------------

                    try:
                        memory_context = (
                            self.long_term_memory.recall_context(
                                routing_text
                            )
                        )
                    except Exception:
                        memory_context = ""

                    agent_task = (
                        routing_text
                        + (
                            "\n\n[USER MEMORY — use naturally when "
                            "relevant]\n"
                            + memory_context
                            + "\n[END USER MEMORY]"
                            if memory_context
                            else ""
                        )
                    )

                    response = (
                        self.run_level2(
                            agent_task,
                            classification
                        )
                    )

                    # ---------------------------------
                    # RECORD LEVEL 2 ENTITY PROVENANCE
                    # ---------------------------------

                    self._record_level2_entities(
                        classification, response
                    )

                # -------------------------------------------------
                # LEVEL 1
                # -------------------------------------------------

                else:

                    print(
                        "[Genesis Core] "
                        "Processing Level 1 conversation..."
                    )

                    response = (
                        self._handle_unmatched_request(
                            routing_text
                        )
                    )

                    if response is None:

                        # ---------------------------------
                        # LONG-TERM MEMORY → CONVERSATION
                        # ---------------------------------

                        try:
                            enriched = (
                                self.long_term_memory.enrich_prompt(
                                    prepared_message
                                )
                            )
                        except Exception:
                            enriched = prepared_message

                        response = (
                            self.brain.think(
                                enriched
                            )
                        )

            except Exception as error:

                print(
                    "[Genesis] "
                    f"Request failed: {error}"
                )

                response = (
                    "I encountered a problem while "
                    "processing that request. "
                    "The error has been isolated "
                    "to this request."
                )

            # -------------------------------------------------
            # FINAL RESPONSE
            # -------------------------------------------------

            print(
                f"\nGenesis: {response}"
            )

            self.conversation.add_message(
                "assistant",
                response
            )


# =========================================================
# APPLICATION ENTRY POINT
# =========================================================

def main():

    genesis = GenesisOS()

    genesis.run()


if __name__ == "__main__":

    main()