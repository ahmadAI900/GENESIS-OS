"""Structural guards: core classes must keep the members they have.

WHY THIS EXISTS
---------------
The last regression in this project was syntactically valid and
behaviorally destructive: a mis-indented insertion left `GenesisOS`
with 3 of its 26 members. Every method after the insertion point
became a nested function of the new module-level helper. Python
parsed the file without complaint, so a plain import test passed,
and the fast gate never saw it -- the 22 broken tests were all
`live`-marked and therefore excluded.

This file is the guard that class of failure needs. It pins the
PUBLIC member names of each core class. Losing one fails here, by
name, in the fast gate.

Subset semantics: ADDING a member is allowed and passes. REMOVING or
relocating one fails and names it. A class that shrank has usually
been truncated by an editing accident rather than designed.

Generated on 2026-10-09 from the live classes, then committed as
literals on purpose: a census generated from the live object at run
time would always agree with itself and would catch nothing.
"""

import pytest

# (label, import path for humans, pinned public member names)
PINNED = (
    (
        "GenesisOS",
        "genesis.GenesisOS",
        {
            "classify",
            "command",
            "plan_level3_objective",
            "run",
            "run_level2",
            "run_level3",
            "run_level3_workflow",
            "run_multi_agent",
            "show_startup",
            "synthesize_multi_agent_results",
        },
    ),
    (
        "ActionExecutor",
        "genesis_os.action_executor.ActionExecutor",
        {
            "EXECUTION_CONTRACT",
            "MINIMUM_CONFIDENCE",
            "VERSION",
            "execute",
        },
    ),
    (
        "AgentFrameworkAdapter",
        "genesis_os.agent_framework_adapter.AgentFrameworkAdapter",
        {
            "aexecute_capability",
            "build_plan",
            "build_tool_func",
            "build_tools",
            "describe_capability",
            "execute_capability",
            "execute_gui_paste_text_sync",
            "execute_plan",
            "invoke_sequence",
        },
    ),
    (
        "ApprovalStore",
        "genesis_os.approval_store.ApprovalStore",
        {
            "approve",
            "consume_token",
            "get_default",
            "issue_token",
            "pending",
            "reject",
            "request",
            "status",
        },
    ),
    (
        "approval_channel (module functions)",
        "genesis_os.approval_channel (module-level)",
        {
            "Any",
            "ApprovalChannel",
            "ApprovalRequest",
            "ApprovalStore",
            "Path",
            "append_audit",
            "arguments_escape_workspace",
            "auto_approve_option_names",
            "build_request",
            "dataclass",
            "field",
            "issue_authorization_grant",
            "path_is_protected",
            "read_audit",
            "render_prompt",
            "workspace_root",
        },
    ),
    (
        "LLMIntentResolver",
        "genesis_os.llm_intent_resolver.LLMIntentResolver",
        {
            "ACTIONABLE",
            "AMBIGUOUS",
            "BLOCKED",
            "PROPOSAL_CONFIDENCE_CAP",
            "VERSION",
            "arbitrate_capabilities",
            "arbitration_probe",
            "cross_domain_contradiction",
            "deterministic_evidence_is_decisive",
            "domain_tokens",
            "evaluate_grounding",
            "grounded_capability",
            "grounding_evidence",
            "lexical_actionability",
            "looks_actionable",
            "reset_domain_vocab",
            "resolve",
        },
    ),
    (
        "WorkflowDecisionEngine",
        "agents.workflow_decision.WorkflowDecisionEngine",
        {
            "VERSION",
            "decide",
            "explain",
        },
    ),
    (
        "CapabilityRegistry",
        "genesis_os.capability_registry.CapabilityRegistry",
        {
            "APPLICATION",
            "BROWSER",
            "DATA",
            "DOCUMENT",
            "FILESYSTEM",
            "NETWORK",
            "PROCESS",
            "SYSTEM",
            "VERSION",
            "by_category",
            "classify",
            "clear",
            "count",
            "is_dangerous",
            "operations",
            "serialize",
            "to_dict",
            "unregister",
        },
    ),
    (
        "CapabilityResolver",
        "genesis_os.capability_resolver.CapabilityResolver",
        {
            "VERSION",
            "resolve",
            "resolve_operation",
        },
    ),
)


def _resolve(label):
    if label == "GenesisOS":
        import genesis
        return genesis.GenesisOS
    if label == "ActionExecutor":
        from genesis_os.action_executor import ActionExecutor
        return ActionExecutor
    if label == "AgentFrameworkAdapter":
        import genesis_os.agent_framework_adapter as m
        return m.AgentFrameworkAdapter
    if label == "ApprovalStore":
        from genesis_os.approval_store import ApprovalStore
        return ApprovalStore
    if label == "approval_channel (module functions)":
        import genesis_os.approval_channel as m
        return m
    if label == "LLMIntentResolver":
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        return LLMIntentResolver
    if label == "WorkflowDecisionEngine":
        from agents.workflow_decision import WorkflowDecisionEngine
        return WorkflowDecisionEngine
    if label == "CapabilityRegistry":
        from genesis_os.capability_registry import CapabilityRegistry
        return CapabilityRegistry
    if label == "CapabilityResolver":
        from genesis_os.capability_resolver import CapabilityResolver
        return CapabilityResolver
    raise AssertionError(label)


@pytest.mark.parametrize("label,where,pinned", PINNED,
                         ids=[p[0] for p in PINNED])
def test_core_class_keeps_its_public_members(label, where, pinned):
    """Every pinned member must still exist. Missing ones are named."""
    target = _resolve(label)
    missing = [name for name in pinned if not hasattr(target, name)]
    assert not missing, (
        f"{where} lost {len(missing)} public member(s): {missing}"
    )


@pytest.mark.parametrize("label,where,pinned", PINNED,
                         ids=[p[0] for p in PINNED])
def test_pinned_members_are_callable_or_class_attributes(label, where, pinned):
    """A member that exists but is None is as broken as a missing one.

    The truncation regression did not delete attributes; it moved them
    out of the class body into another function's body. Checking
    presence alone catches the common case; checking the value is not
    None catches a partial splice.
    """
    target = _resolve(label)
    hollow = [n for n in pinned if hasattr(target, n)
              and getattr(target, n, None) is None]
    assert not hollow, f"{where} has None-valued members: {hollow}"
