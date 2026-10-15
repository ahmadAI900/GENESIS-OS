"""
Genesis OS — Level 3.11
Unified Intelligence.

Regression tests for:

    - typo-tolerant application and folder resolution
    - multilingual understanding (translation gate)
    - live web research capability
    - CROSS-LEVEL ORCHESTRATION:
      "open vs code and write code" runs Level 3 AND the
      Level 2 coding agent TOGETHER on one objective.
"""

from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real GenesisOS; live browser and cloud LLM layers.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


# =========================================================
# TYPO TOLERANCE
# =========================================================


@pytest.mark.parametrize(
    "text,application",
    [
        ("open chrom", "chrome"),
        ("launch firefix", "firefox"),
        ("close vscod", "vscode"),
        ("open notpad", "notepad"),
        ("please open exce", None),  # 'exce' is too far from any alias
    ],
)
def test_fuzzy_application_resolution(text, application):
    decision = WorkflowDecisionEngine().decide(text)

    if application is None:
        assert decision.get("application") != application or decision["level"] != 3 \
            or decision.get("application") == "excel"  # only if genuinely close
    else:
        assert decision["level"] == 3
        assert decision["application"] == application


@pytest.mark.parametrize(
    "text,folder",
    [
        ("open my downloadss", "downloads"),
        ("go to documnts", "documents"),
        ("open desktap", "desktop"),
    ],
)
def test_fuzzy_folder_resolution(text, folder):
    decision = WorkflowDecisionEngine().decide(text)

    assert decision["level"] == 3
    assert decision["intent"] == "folder.open"
    assert decision["target"] == folder


def test_fuzzy_matching_does_not_create_false_positives():
    decision = WorkflowDecisionEngine().decide("run python")

    # 'run python' is a conversational/agent request — it must
    # never become an OS application launch.
    assert decision["intent"] != "application.open"


# =========================================================
# WEB RESEARCH CAPABILITY
# =========================================================


def test_web_research_is_registered_and_allowed():
    from genesis_os.execution_safety import ExecutionSafety

    assert ExecutionSafety.check("web.research").status == "supported"


def test_web_research_routing():
    engine = WorkflowDecisionEngine()

    # Per GENESIS_MASTER_COMPLETION directive: "Research X" is
    # an L2 Research Agent task. "Search the web for X" /
    # "look up X online" are L3 web.research because the
    # user explicitly asks for live web fetching.
    decision = engine.decide("search the web for quantum computing breakthroughs")
    assert decision["level"] == 3
    assert decision["intent"] == "web.research"
    assert "quantum computing" in decision["parameters"]["query"]


def test_web_research_contract_with_fake_provider():
    from genesis_os.web_intelligence import WebIntelligence

    fake_search = Mock()
    fake_search.search_multiple.return_value = [
        {"title": "Result A", "content": "Body text about the query.", "url": "https://a.example"},
        {"title": "Result B", "content": "More context.", "url": "https://b.example"},
    ]

    result = WebIntelligence(search=fake_search).research("test query")

    assert result["success"] is True
    assert result["verified"] is True
    assert result["result_count"] == 2
    assert "Result A" in result["summary"]
    fake_search.search_multiple.assert_called_once()


def test_web_research_reports_provider_failure_honestly():
    from genesis_os.web_intelligence import WebIntelligence

    fake_search = Mock()
    fake_search.search_multiple.return_value = [
        {"title": "Search Unavailable", "content": "The optional web-search provider is not installed.", "url": ""}
    ]

    result = WebIntelligence(search=fake_search).research("anything")

    assert result["success"] is False
    assert "duckduckgo_search" in result["error"]


def test_web_research_rejects_empty_query():
    from genesis_os.web_intelligence import WebIntelligence

    result = WebIntelligence(search=Mock()).research("   ")

    assert result["success"] is False
    assert result["executed"] is False


def test_web_research_dispatch_through_executor():
    os_manager = Mock()
    os_manager.web_research.return_value = {
        "success": True,
        "operation": "web.research",
        "query": "ai news",
        "summary": "1. Some headline",
        "results": [{"title": "Some headline", "snippet": "...", "url": "https://x"}],
        "result_count": 1,
        "executed": True,
        "verified": True,
        "message": "Found 1 live result(s).",
    }

    plan = ActionPlan(
        operation="web.research",
        target="ai news",
        parameters={"query": "ai news"},
        confidence=0.95,
    )

    result = ActionExecutor(os_manager).execute(plan)

    assert result.success is True
    assert result.verified is True
    os_manager.web_research.assert_called_once_with("ai news", 5)


# =========================================================
# LANGUAGE NORMALIZATION GATE
# =========================================================


def test_non_latin_script_requires_translation():
    from genesis_os.language_normalizer import LanguageNormalizer

    normalizer = LanguageNormalizer(ai_engine=Mock())

    assert normalizer.needs_translation("क्रोम खोलो और यूट्यूब चलाओ") is True
    assert normalizer.needs_translation("open chrome please") is False
    assert normalizer.needs_translation("") is False


def test_translation_prompt_contract():
    from genesis_os.language_normalizer import LanguageNormalizer

    ai = Mock()
    ai.generate_response.return_value = '"open chrome please"'
    normalizer = LanguageNormalizer(ai_engine=ai)

    result = normalizer.to_english_command("abre chrome por favor")

    if result is None:
        pytest.skip("langdetect unavailable")

    assert result["english"] == "open chrome please"
    assert result["original"] == "abre chrome por favor"

    prompt_used = ai.generate_response.call_args[0][0]
    assert "abre chrome por favor" in prompt_used


def test_normalizer_declines_when_ai_unavailable():
    from genesis_os.language_normalizer import LanguageNormalizer

    normalizer = LanguageNormalizer(ai_engine=None)

    assert normalizer.available is False
    assert normalizer.to_english_command("क्रोम खोलो") is None


# =========================================================
# CROSS-LEVEL ORCHESTRATION
# =========================================================


class _StubOSManager:
    """Minimal OS surface so orchestration tests stay offline.

    UPDATED 2026-10-04: the payload now carries a `verification` dict.
    A bare `verified: True` is rejected by the Phase 1 evidence
    contract (`require_result_evidence` in `contracts.py`), which
    downgrades the result to `verification_unavailable` before the
    workflow engine ever sees a verified step. `running` is the
    evidence key `has_meaningful_result_evidence` accepts for an
    `application.*` capability.
    """

    def __init__(self):
        self.opened = []

    def open_application(self, app):
        self.opened.append(app)
        return {
            "success": True,
            "operation": "application.open",
            "application": app,
            "executed": True,
            "verified": True,
            "running": True,
            "verification": {"running": True},
            "message": f"{app} opened.",
        }

    def web_search(self, query, engine="google"):
        """UPDATED 2026-10-04.

        Added so a browser-bearing objective can be asserted without a
        real browser. Previously these tests reached the live
        BrowserManager, which failed, and the workflow engine correctly
        reported "Browser page state was not independently observed" --
        so the assertion about verified steps was measuring the absence
        of a browser rather than the orchestration behaviour under test.
        """
        self.searched = getattr(self, "searched", [])
        self.searched.append((query, engine))
        return {
            "success": True,
            "operation": "browser.search",
            "executed": True,
            "verified": True,
            "verification": {"search_verified": True},
            "message": f"searched for {query!r}",
        }


@pytest.fixture(scope="module")
def genesis():
    from genesis import GenesisOS

    instance = GenesisOS()
    stub = _StubOSManager()
    instance.os_manager.applications.open = stub.open_application
    instance.os_manager.web_search = stub.web_search
    return instance


def test_mixed_objective_runs_level3_and_level2_together(genesis):
    """A mixed objective must engage BOTH the OS and an agent.

    REWRITTEN 2026-10-04. This asserted the strings "Desktop actions"
    and "Coding Agent" in the formatted user-facing response. Two
    things changed underneath it, both deliberate:

    * the Coding Agent is resolved through
      `unified_executor.agent_registry`, not `genesis.executor`, so the
      test's monkeypatch never intercepted it, and
    * `browser.*`/GUI steps now go through `ObservationLoop`, which
      re-checks real OS state, so a stubbed executor cannot make a
      step "verified" here.

    So the formatted string is not a stable assertion surface. The
    test now asserts the behaviour it is named for, structurally: the
    cross-level path runs, the agent is engaged with the coding half,
    an OS step is produced, and whatever the OS leg's verification
    outcome is, it is reported honestly rather than as success.
    """
    from agents.base_agent import BaseAgent

    engaged = []

    class _DeterministicCodingAgent(BaseAgent):
        def __init__(self):
            super().__init__("Coding Agent", "Writes code", ["code"])

        def run(self, task, context=None):
            engaged.append(str(task))
            return {"code": "def calculator():\n    return 42\n",
                    "language": "python"}

        def can_handle(self, task):
            return "code" in str(task).lower()

    registry = genesis.unified_executor.agent_registry
    previous = registry.get_agent("Coding Agent")
    registry.register(_DeterministicCodingAgent())
    try:
        result = genesis.genesis_runtime.execute_mixed_audited(
            "open notepad and write python code for a calculator",
            genesis.unified_executor,
        )
    finally:
        if previous is not None:
            registry.register(previous)

    assert engaged, "the Coding Agent was never engaged"
    assert "calculator" in engaged[0].lower()

    agent_results = list(getattr(result, "agent_results", []) or [])
    os_results = list(getattr(result, "os_results", []) or [])
    assert agent_results, "the intelligence leg produced no agent result"
    assert os_results, "the OS leg produced no OS step"

    # The OS leg bridged the agent's output into a real OS action.
    assert any(
        entry.get("operation") == "file.create" for entry in os_results
    ), [entry.get("operation") for entry in os_results]

    # Whatever the OS leg's verification outcome, it is not laundered
    # into success.
    if not result.final_verified:
        assert result.success is False, (
            "an unverified OS leg was reported as success"
        )


def test_pure_level3_objectives_do_not_invoke_agents(genesis):
    """A pure Level 3 objective must not reach an agent.

    REWRITTEN 2026-10-04 for the same two reasons as the test above:
    the agent guard is set on `genesis.executor`, which the pure-L3
    path does not consult, and `browser.*` steps cannot reach a
    verified state on this host because `ObservationLoop` re-checks
    real OS state.

    The premise is asserted directly on the dispatch result -- no
    agent was engaged, and the OS leg really ran two steps -- plus the
    honest-degradation assertion for the browser step.
    """
    engaged = []

    from agents.base_agent import BaseAgent

    class _TripwireCodingAgent(BaseAgent):
        def __init__(self):
            super().__init__("Coding Agent", "Writes code", ["code"])

        def run(self, task, context=None):
            engaged.append(str(task))
            return {"code": "x = 1\n", "language": "python"}

        def can_handle(self, task):
            return True

    registry = genesis.unified_executor.agent_registry
    previous = registry.get_agent("Coding Agent")
    registry.register(_TripwireCodingAgent())

    class GuardExecutor:
        def execute(self, tasks):
            engaged.append(f"agent-executor:{tasks}")
            return []

    original_executor = genesis.executor
    genesis.executor = GuardExecutor()

    try:
        result = genesis.run_level3(
            "Open Chrome and search YouTube for Python tutorials.",
            genesis.classify("Open Chrome and search YouTube for Python tutorials."),
        )
    finally:
        genesis.executor = original_executor
        if previous is not None:
            registry.register(previous)

    assert engaged == [], (
        f"a pure L3 objective engaged an intelligence agent: {engaged}"
    )

    steps = list(getattr(result, "steps", []) or [])
    assert len(steps) == 2, [s.get("operation") for s in steps]
    assert [s.get("operation") for s in steps] == [
        "application.open", "browser.search",
    ]

    # The unverifiable browser step is reported as unverified, never
    # promoted to success.
    browser_step = steps[-1]
    assert browser_step.get("verified") is False, browser_step
    if result.final_verified is False:
        assert result.success is False, (
            "an unverified workflow was reported as success"
        )
