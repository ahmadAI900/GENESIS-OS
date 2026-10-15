"""
Genesis OS — Level 3.9
Multi-Step Natural-Language Workflows

Verifies that a natural multi-step objective such as

    "Open Chrome and search YouTube for Python tutorials"

is understood, decomposed, target-resolved, executed through the
ActionExecutor safety gate, and verified step-by-step — without
any hardcoded special-case workflow.
"""

from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.browser_manager import BrowserManager
from genesis_os.objective_understanding import ObjectiveUnderstanding
from genesis_os.os_manager import OSManager
from genesis_os.workflow_decomposer import WorkflowDecomposer
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.workflow_models import WorkflowPlan, WorkflowStep
from genesis_os.workflow_target_resolver import WorkflowTargetResolver
from genesis_os.target_discovery import TargetDiscovery
from genesis_os.file_target_provider import FileTargetProvider
from genesis_os.folder_target_provider import FolderTargetProvider

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: constructs a real BrowserManager.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


# =========================================================
# HELPERS
# =========================================================


def _build_workflow(objective_text):
    understanding = ObjectiveUnderstanding(
        WorkflowDecisionEngine()
    ).understand(objective_text)

    decomposition = WorkflowDecomposer().decompose(
        understanding,
    )

    return understanding, decomposition


def _verification_evidence(operation):
    """Capability-specific evidence for a fabricated verified result.

    UPDATED 2026-10-04. `_verified_result` used to return a bare
    `verified: True`. The Phase 1 evidence contract
    (`PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md`: "a `verified=true`
    result means the post-state was actually observed, not just that the
    provider reported success") rejects that: `require_result_evidence`
    raises unless `verified=True` is backed by capability-specific
    evidence, and `ActionExecutor._enforce_execution_contract` then
    downgrades the result to `verification_unavailable`. Every test in
    this file therefore stopped at the evidence gate before reaching
    the behaviour it was written to prove.

    The keys below are the ones `contracts.has_meaningful_result_evidence`
    actually accepts, so these fixtures now represent a legitimately
    observed result rather than a bare claim.
    """
    if operation.startswith("application."):
        return {"running": True}
    if operation in {"browser.search"}:
        return {"search_verified": True}
    if operation in {"browser.open_url", "browser.navigate"}:
        return {"requested_url": "https://example.com",
                "actual_url": "https://example.com"}
    if operation.startswith("file.") or operation.startswith("folder."):
        return {"file_matches": True}
    return {"all_passed": True}


def _verified_result(operation):
    def _inner(*args, **kwargs):
        return {
            "success": True,
            "operation": operation,
            "executed": True,
            "verified": True,
            "verification": _verification_evidence(operation),
            "message": f"{operation} verified.",
        }

    return _inner


# =========================================================
# OBJECTIVE UNDERSTANDING + DECOMPOSITION
# =========================================================


def test_browser_objective_decomposes_into_two_steps():
    understanding, decomposition = _build_workflow(
        "Open Chrome and search YouTube for Python tutorials."
    )

    assert len(understanding.steps) == 2
    assert decomposition.executable is True
    assert decomposition.workflow is not None
    assert len(decomposition.workflow.steps) == 2

    first = decomposition.workflow.steps[0].plan
    second = decomposition.workflow.steps[1].plan

    assert first.operation == "application.open"
    assert first.application == "chrome"

    assert second.operation == "browser.search"
    assert second.parameters["engine"] == "youtube"
    assert second.parameters["query"] == "python tutorials"


def test_sequenced_objective_decomposes_in_order():
    _, decomposition = _build_workflow(
        "open chrome then search google for latest AI news"
    )

    assert decomposition.executable is True

    operations = [
        step.plan.operation
        for step in decomposition.workflow.steps
    ]

    assert operations == [
        "application.open",
        "browser.search",
    ]


def test_mixed_objective_requires_clarification():
    """
    A non-OS part of a compound objective must block automatic
    execution instead of being silently skipped.
    """

    understanding, decomposition = _build_workflow(
        "open chrome and write a poem"
    )

    assert decomposition.executable is False
    assert decomposition.requires_clarification is True


def test_dependency_chain_is_sequential():
    _, decomposition = _build_workflow(
        "Open Chrome and search YouTube for Python tutorials."
    )

    steps = decomposition.workflow.steps

    assert steps[0].depends_on == ()
    assert steps[1].depends_on == ("step-1",)


# =========================================================
# WORKFLOW TARGET RESOLUTION BOUNDARIES
# =========================================================


def test_resolver_leaves_application_and_browser_steps_untouched():
    _, decomposition = _build_workflow(
        "Open Chrome and search YouTube for Python tutorials."
    )

    discovery = TargetDiscovery(
        file_provider=FileTargetProvider(),
        folder_provider=FolderTargetProvider(),
    )

    resolver = WorkflowTargetResolver(discovery)

    updated, resolutions = resolver.resolve_workflow(
        decomposition.workflow
    )

    # Application/browser targets are resolved by their own
    # execution managers, not by generic filesystem discovery.
    assert resolutions == {}
    assert updated.steps[0].plan.target == "chrome"
    assert updated.steps[1].plan.parameters["engine"] == "youtube"


def test_resolver_resolves_semantic_folder_step(tmp_path):
    from dataclasses import replace as dc_replace
    from genesis_os.action_plan import ActionPlan

    plan = ActionPlan(operation="folder.open", target="downloads")
    step = WorkflowStep(step_id="step-1", plan=plan)
    workflow = WorkflowPlan(objective="open downloads", steps=(step,))

    discovery = TargetDiscovery(
        file_provider=FileTargetProvider(),
        folder_provider=FolderTargetProvider(),
    )

    updated, resolutions = WorkflowTargetResolver(discovery).resolve_workflow(workflow)

    expected = str((Path_home() / "Downloads").resolve())
    assert resolutions["step-1"].successful is True
    assert updated.steps[0].plan.target == expected


def Path_home():
    from pathlib import Path
    return Path.home()


# =========================================================
# UNIVERSAL ENGINE EXECUTION THROUGH THE SAFETY GATE
# =========================================================


def test_multi_step_workflow_executes_and_verifies():
    _, decomposition = _build_workflow(
        "Open Chrome and search YouTube for Python tutorials."
    )

    os_manager = Mock(spec=OSManager)
    os_manager.open_application.side_effect = _verified_result("application.open")
    os_manager.web_search.side_effect = _verified_result("browser.search")

    engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))

    result = engine.execute(decomposition.workflow)

    assert result.success is True
    assert result.final_verified is True
    assert len(result.steps) == 2

    os_manager.open_application.assert_called_once_with("chrome")
    os_manager.web_search.assert_called_once_with("python tutorials", "youtube")


def test_multi_step_workflow_stops_on_failed_first_step():
    _, decomposition = _build_workflow(
        "Open Chrome and search YouTube for Python tutorials."
    )

    os_manager = Mock(spec=OSManager)
    os_manager.open_application.return_value = {
        "success": False,
        "operation": "application.open",
        "error": "Chrome not found",
        "executed": True,
        "verified": False,
    }

    engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))

    result = engine.execute(decomposition.workflow)

    assert result.success is False
    assert result.final_verified is False
    # The second step must never run after an unverified first step.
    os_manager.web_search.assert_not_called()
    assert result.state["failed_step"] == "step-1"


def test_confirmation_required_stops_entire_workflow(tmp_path):
    from genesis_os.action_plan import ActionPlan

    # A move whose destination ALREADY EXISTS escalates to Tier 1 via
    # the overwrite evaluator. A move to a free destination is Tier 2
    # and would run, so this pins the case that actually stops the
    # workflow under the blast-radius model.
    occupied = tmp_path / "b.txt"
    occupied.write_text("existing")

    plans = [
        ActionPlan(operation="application.open", target="notepad"),
        ActionPlan(
            operation="file.move",
            target="a.txt",
            parameters={"destination": str(occupied)},
        ),
    ]
    steps = tuple(
        WorkflowStep(step_id=f"step-{i}", plan=plan)
        for i, plan in enumerate(plans, start=1)
    )
    workflow = WorkflowPlan(objective="compound", steps=steps)

    os_manager = Mock(spec=OSManager)
    os_manager.open_application.side_effect = _verified_result("application.open")

    engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))
    result = engine.execute(workflow)

    assert result.success is False
    assert result.status == "confirmation_required"


# =========================================================
# BROWSER MANAGER
# =========================================================


@pytest.mark.parametrize(
    "engine_name,prefix",
    [
        ("google", "https://www.google.com/search?q="),
        ("youtube", "https://www.youtube.com/results?search_query="),
        ("bing", "https://www.bing.com/search?q="),
        ("duckduckgo", "https://duckduckgo.com/?q="),
    ],
)
def test_search_engines_build_safe_urls(engine_name, prefix):
    manager = BrowserManager()

    opened = {}

    original = manager.open_url

    def capturing(url, session_id="default"):
        opened["url"] = url
        return {"success": True, "operation": "browser.open_url", "url": url,
                "executed": True, "verified": True}

    manager.open_url = capturing
    result = manager.search("python tutorials", engine_name)

    assert result["success"] is True
    assert opened["url"] == prefix + "python+tutorials"
    assert result["engine"] == engine_name


def test_search_rejects_empty_query():
    result = BrowserManager().search("   ")
    assert result["success"] is False
