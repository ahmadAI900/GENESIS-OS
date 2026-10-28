"""
Genesis OS — Level 3 Mixed Intelligence + OS Workflow Tests.
"""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from agents.agent_registry import AgentRegistry
from agents.base_agent import BaseAgent
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.unified_executor import (
    AgentCapabilityMapper,
    MixedWorkflowPlanner,
    UnifiedExecutor,
    create_unified_executor,
)
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.os_manager import OSManager
from genesis_os.session_state import SessionState
from genesis_os.context_resolver import ContextResolver
from genesis_os.action_plan import ActionPlan
from genesis_os.workflow_models import WorkflowPlan, WorkflowStep


class MockResearchAgent(BaseAgent):
    def __init__(self):
        super().__init__("Research Agent", "Researches topics", ["research"])

    def run(self, task, context=None):
        return {"findings": "Research results for " + task}

    def can_handle(self, task):
        task_lower = task.lower()
        return any(kw in task_lower for kw in ["research", "investigate", "find information"])


class MockDataAgent(BaseAgent):
    def __init__(self):
        super().__init__("Data Agent", "Analyzes data", ["data", "analyze"])

    def run(self, task, context=None):
        return {"analysis": "Data analysis for " + task, "data": {"rows": 10, "cols": 5}}

    def can_handle(self, task):
        task_lower = task.lower()
        return any(kw in task_lower for kw in ["analyze", "data", "csv", "excel", "statistics"])


class MockHTMLAgent(BaseAgent):
    def __init__(self):
        super().__init__("Coding Agent", "Writes HTML", ["code", "html"])

    def run(self, task, context=None):
        return {"code": "<html><body>generated</body></html>", "language": "html"}

    def can_handle(self, task):
        return "code" in task.lower() or "website" in task.lower()


class MockCodingAgent(BaseAgent):
    def __init__(self):
        super().__init__("Coding Agent", "Writes code", ["code", "debug"])

    def run(self, task, context=None):
        return {"code": "print('Hello')", "language": "python"}

    def can_handle(self, task):
        task_lower = task.lower()
        return any(kw in task_lower for kw in ["code", "program", "script", "debug", "fix"])


def test_agent_capability_mapper_identifies_research_agent():
    """Test that research-related queries map to Research Agent."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    mapper = AgentCapabilityMapper(registry)

    agents = mapper.identify_required_agents("Research the best laptops")
    assert "Research Agent" in agents


def test_agent_capability_mapper_identifies_coding_agent():
    """Test that coding-related queries map to Coding Agent."""
    registry = AgentRegistry()
    registry.register(MockCodingAgent())

    mapper = AgentCapabilityMapper(registry)

    agents = mapper.identify_required_agents("Write Python code to sort a list")
    assert "Coding Agent" in agents


def test_agent_capability_mapper_identifies_data_agent():
    """Test that data-related queries map to Data Agent."""
    registry = AgentRegistry()
    registry.register(MockDataAgent())

    mapper = AgentCapabilityMapper(registry)

    agents = mapper.identify_required_agents("Analyze this CSV data")
    assert "Data Agent" in agents


def test_agent_capability_mapper_multiple_agents():
    """Test that complex queries identify multiple agents."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())
    registry.register(MockDataAgent())
    registry.register(MockCodingAgent())

    mapper = AgentCapabilityMapper(registry)

    agents = mapper.identify_required_agents("Research laptops, analyze the data, and write a Python script")
    assert "Research Agent" in agents
    assert "Data Agent" in agents
    assert "Coding Agent" in agents


def test_agent_capability_mapper_order():
    """Test that agents are ordered by typical pipeline."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())
    registry.register(MockDataAgent())
    registry.register(MockCodingAgent())

    mapper = AgentCapabilityMapper(registry)

    agents = mapper.identify_required_agents("Research, analyze data, and write code")
    # Research should come before Data, Data before Coding
    research_idx = agents.index("Research Agent")
    data_idx = agents.index("Data Agent")
    coding_idx = agents.index("Coding Agent")
    assert research_idx < data_idx < coding_idx


def test_mixed_workflow_planner_builds_agent_tasks():
    """Test that planner creates agent tasks with dependencies."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())
    registry.register(MockDataAgent())

    decision_engine = WorkflowDecisionEngine()
    context_resolver = ContextResolver()
    mapper = AgentCapabilityMapper(registry)

    planner = MixedWorkflowPlanner(mapper, decision_engine, context_resolver)

    plan = planner.plan("Research laptops and analyze the data")

    assert len(plan.agent_tasks) == 2
    assert plan.agent_tasks[0].agent_name == "Research Agent"
    assert plan.agent_tasks[1].agent_name == "Data Agent"
    # Data Agent should depend on Research Agent
    assert plan.agent_tasks[1].depends_on == ("agent-0",)


def test_mixed_workflow_planner_detects_os_intent():
    """Test that planner detects OS intent and creates OS steps."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    decision_engine = WorkflowDecisionEngine()
    context_resolver = ContextResolver()
    mapper = AgentCapabilityMapper(registry)

    planner = MixedWorkflowPlanner(mapper, decision_engine, context_resolver)

    plan = planner.plan("Research laptops and open Chrome")

    assert len(plan.agent_tasks) == 1
    assert len(plan.os_steps) == 1
    assert plan.os_steps[0].action_plan.operation == "application.open"
    assert plan.os_steps[0].action_plan.target == "chrome"
    # OS step should depend on agent
    assert plan.os_steps[0].depends_on == ("agent-0",)


def test_unified_executor_creation():
    """Test creating unified executor."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    os_manager = Mock(spec=OSManager)
    action_executor = ActionExecutor(os_manager)
    workflow_engine = UniversalDesktopWorkflowEngine(action_executor, os_manager=os_manager)
    session_state = SessionState(os_manager)
    context_resolver = ContextResolver(session_state)
    decision_engine = WorkflowDecisionEngine()

    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=context_resolver,
        decision_engine=decision_engine,
    )

    assert executor is not None
    assert executor.agent_registry == registry
    assert executor.workflow_engine == workflow_engine


def test_unified_executor_executes_agent_only_workflow():
    """Test executor runs agent-only workflow."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    os_manager = Mock(spec=OSManager)
    action_executor = ActionExecutor(os_manager)
    workflow_engine = UniversalDesktopWorkflowEngine(action_executor, os_manager=os_manager)
    session_state = SessionState(os_manager)
    context_resolver = ContextResolver(session_state)
    decision_engine = WorkflowDecisionEngine()

    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=context_resolver,
        decision_engine=decision_engine,
    )

    result = executor.execute("Research the best laptops")

    assert result.success is True
    assert len(result.agent_results) == 1
    assert result.agent_results[0]["agent"] == "Research Agent"
    assert result.agent_results[0]["success"] is True
    assert len(result.os_results) == 0


def test_unified_executor_executes_mixed_workflow():
    """Test executor runs mixed agent + OS workflow."""
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    os_manager = Mock(spec=OSManager)
    # Mock the application.open to succeed
    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "executed": True,
            "verified": True,
            "running": True,
            "message": "Opened Chrome",
    }
    os_manager.inspect_application.return_value = {
        "running": True,
        "application": "chrome",
    }

    action_executor = ActionExecutor(os_manager)
    workflow_engine = UniversalDesktopWorkflowEngine(action_executor, os_manager=os_manager)
    session_state = SessionState(os_manager)
    context_resolver = ContextResolver(session_state)
    decision_engine = WorkflowDecisionEngine()

    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=context_resolver,
        decision_engine=decision_engine,
    )

    result = executor.execute("Research laptops and open Chrome")

    assert result.success is True
    assert len(result.agent_results) == 1
    assert result.agent_results[0]["agent"] == "Research Agent"
    assert len(result.os_results) >= 1  # At least one OS step executed


def test_mixed_workflow_passes_agent_result_to_l3(workspace_root, monkeypatch):
    """Directive requirement: "research biology and save the result
    to my Biology folder" must invoke the L2 Research Agent, pass
    its structured result into L3, and the executor must refine
    L3 steps based on the agent output.

    cwd is set to the workspace root because the workflow's folder
    target ("Biology") is RELATIVE, and a relative target resolves
    against cwd. This test is about agent-result routing, not about
    where the folder lands, so it is retargeted rather than gated.
    """
    monkeypatch.chdir(workspace_root)
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    os_manager = Mock(spec=OSManager)
    os_manager.create_folder.return_value = {
        "success": True,
        "operation": "folder.create",
        "executed": True,
            "verified": True,
            "folder_exists": True,
            "post_state_matches": True,
            "message": "Folder created",
    }
    os_manager.inspect_folder.return_value = {
        "success": True,
        "operation": "folder.inspect",
        "exists": True,
        "item_count": 0,
        "verified": True,
    }
    os_manager.create_file.return_value = {
        "success": True,
        "operation": "file.create",
        "executed": True,
            "verified": True,
            "file_exists": True,
            "content_match": True,
            "post_state_matches": True,
            "message": "File created",
    }
    os_manager.inspect_file.return_value = {
        "success": True,
        "operation": "file.inspect",
        "exists": True,
        "size": 0,
        "verified": True,
    }
    os_manager.open_folder.return_value = {
        "success": True,
        "operation": "folder.open",
        "executed": True,
        "verified": True,
        "message": "Folder opened",
    }

    action_executor = ActionExecutor(os_manager)
    workflow_engine = UniversalDesktopWorkflowEngine(action_executor, os_manager=os_manager)
    session_state = SessionState(os_manager)
    context_resolver = ContextResolver(session_state)
    decision_engine = WorkflowDecisionEngine()

    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=context_resolver,
        decision_engine=decision_engine,
    )

    result = executor.execute(
        "research biology and save the result to my Biology folder"
    )

    assert result.success is True
    # The L2 Research Agent must have been invoked.
    assert len(result.agent_results) == 1
    agent_result = result.agent_results[0]
    assert agent_result["agent"] == "Research Agent"
    assert agent_result["success"] is True
    # The agent's structured output must be available for the L3
    # planner's refinement step.
    assert "response" in agent_result or "findings" in agent_result


def test_mixed_workflow_creates_file_from_agent_output(workspace_root, monkeypatch):
    # Relative targets in this workflow (Biology, the generated file)
    # resolve against cwd, so cwd is set to the workspace root. The test is
    # about routing and content bridging, not about where files land.
    monkeypatch.chdir(workspace_root)
    """Directive requirement: the L2 agent output drives the L3
    filesystem work. When the Research Agent produces structured
    findings, the executor's refinement must produce at least
    one OS step that touches the filesystem to persist the result.
    """
    registry = AgentRegistry()
    registry.register(MockResearchAgent())

    os_manager = Mock(spec=OSManager)
    os_manager.create_folder.return_value = {
        "success": True,
        "operation": "folder.create",
        "executed": True,
            "verified": True,
            "folder_exists": True,
            "post_state_matches": True,
            "message": "Folder created",
    }
    os_manager.inspect_folder.return_value = {
        "success": True,
        "operation": "folder.inspect",
        "exists": True,
        "item_count": 0,
        "verified": True,
    }
    os_manager.create_file.return_value = {
        "success": True,
        "operation": "file.create",
        "executed": True,
            "verified": True,
            "file_exists": True,
            "content_match": True,
            "post_state_matches": True,
            "message": "File created",
    }
    os_manager.inspect_file.return_value = {
        "success": True,
        "operation": "file.inspect",
        "exists": True,
        "size": 0,
        "verified": True,
    }
    os_manager.open_folder.return_value = {
        "success": True,
        "operation": "folder.open",
        "executed": True,
        "verified": True,
        "message": "Folder opened",
    }

    action_executor = ActionExecutor(os_manager)
    workflow_engine = UniversalDesktopWorkflowEngine(action_executor, os_manager=os_manager)
    session_state = SessionState(os_manager)
    context_resolver = ContextResolver(session_state)
    decision_engine = WorkflowDecisionEngine()

    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=context_resolver,
        decision_engine=decision_engine,
    )

    # When the request explicitly says "save to my Biology folder"
    # the L3 clause is "save to ... Biology folder" which routes
    # to folder.open / file.create. The agent clause is "research
    # biology".
    result = executor.execute(
        "research biology and save the result to my Biology folder"
    )

    # At least one OS step must have executed (folder.open for the
    # Biology folder, OR a file.create for the research result).
    assert len(result.os_results) >= 1, (
        f"No OS step executed for mixed L2+L3; "
        f"agent_results={result.agent_results}, "
        f"os_results={result.os_results}"
    )
    # The mixed workflow MUST be marked trustworthy (success=True)
    # even when the L3 OS step succeeds AND the agent succeeded.
    assert result.final_verified is True, (
        f"Mixed workflow final_verified=False; "
        f"success={result.success} message={result.message} "
        f"error={result.error} os_results={result.os_results}"
    )


def test_exact_compound_html_request_bridges_agent_output_to_file_action(
    workspace_root, monkeypatch
):
    monkeypatch.chdir(workspace_root)
    registry = AgentRegistry()
    registry.register(MockHTMLAgent())
    os_manager = Mock(spec=OSManager)
    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "executed": True,
        "verified": True,
        "running": True,
    }
    os_manager.inspect_application.return_value = {
        "success": True,
        "running": True,
        "application": "notepad",
    }
    os_manager.create_file.return_value = {
        "success": True,
        "operation": "file.create",
        "executed": True,
        "verified": True,
        "file_exists": True,
        "content_match": True,
    }
    os_manager.inspect_file.return_value = {
        "success": True,
        "exists": True,
        "identity": {"exists": True},
    }
    os_manager.read_file.return_value = {
        "success": True,
        "content": "<html><body>generated</body></html>",
    }
    workflow_engine = UniversalDesktopWorkflowEngine(
        ActionExecutor(os_manager), os_manager=os_manager
    )
    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=SessionState(os_manager),
        context_resolver=ContextResolver(SessionState(os_manager)),
        decision_engine=WorkflowDecisionEngine(),
    )

    result = executor.execute("open notepad and write html code for website")

    assert result.os_results
    create_call = os_manager.create_file.call_args
    assert create_call is not None
    assert create_call.args[0] == "index.html"
    assert "<html>" in create_call.args[1]


def test_exact_research_pdf_request_routes_and_bridges_content(workspace_root, monkeypatch):
    # Relative targets in this workflow (Biology, the generated file)
    # resolve against cwd, so cwd is set to the workspace root. The test is
    # about routing and content bridging, not about where files land.
    monkeypatch.chdir(workspace_root)
    phrase = "research biology and save it as a pdf"
    decision = WorkflowDecisionEngine().decide(phrase)
    assert decision["level"] == 3
    assert decision["intent"] == "document.create_pdf"

    registry = AgentRegistry()
    registry.register(MockResearchAgent())
    os_manager = Mock(spec=OSManager)
    os_manager.doc_create.return_value = {
        "success": True,
        "operation": "document.create",
        "executed": True,
        "verified": True,
        "file_exists": True,
    }
    os_manager.inspect_file.return_value = {
        "success": True,
        "exists": True,
        "identity": {"exists": True},
    }
    workflow_engine = UniversalDesktopWorkflowEngine(
        ActionExecutor(os_manager), os_manager=os_manager
    )
    session_state = SessionState(os_manager)
    executor = create_unified_executor(
        agent_registry=registry,
        workflow_engine=workflow_engine,
        session_state=session_state,
        context_resolver=ContextResolver(session_state),
        decision_engine=WorkflowDecisionEngine(),
    )

    result = executor.execute(phrase)

    assert result.success is True
    doc_call = os_manager.doc_create.call_args
    assert doc_call is not None
    assert doc_call.args[0] == "research.pdf"
    assert doc_call.kwargs["doc_type"] == "pdf"
    assert "Research results" in doc_call.kwargs["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
