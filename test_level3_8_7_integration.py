from genesis_os.capabilities import (
    CapabilityCategory,
    CapabilityRequirement,
)
from genesis_os.capability_registry import (
    CapabilityRegistry,
)
from genesis_os.capability_resolver import (
    CapabilityResolver,
)
from genesis_os.workflow_capability import (
    WorkflowCapabilityResolver,
)


def test_workflow_capability_constructs_action_plan():
    registry = CapabilityRegistry()
    resolver = CapabilityResolver(registry)
    workflow_capability_resolver = (
        WorkflowCapabilityResolver(resolver)
    )

    requirement = CapabilityRequirement(
        capability_id="application.open",
        category=CapabilityCategory.APPLICATION,
        operation="application.open",
        required_inputs=frozenset({"application"}),
        required_permissions=frozenset({"application.launch"}),
    )

    result = workflow_capability_resolver.construct_plan(
        step_id="step-1",
        requirement=requirement,
        target="chrome",
        application="chrome",
        task="Open Chrome",
    )

    assert result.constructed
    assert result.plan is not None

    assert (
        result.plan.operation
        == "application.open"
    )

    assert (
        result.plan.target
        == "chrome"
    )

    assert (
        result.plan.application
        == "chrome"
    )