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

from genesis_os.dynamic_plan import (
    CapabilityNotResolvedError,
    DynamicPlanConstructor,
    DynamicPlanValidationError,
)
def _build_workflow_capability_resolver():
    registry = CapabilityRegistry()

    resolver = CapabilityResolver(
        registry
    )

    return WorkflowCapabilityResolver(
        resolver
    )


def _build_application_open_binding():
    registry = CapabilityRegistry()

    resolver = CapabilityResolver(
        registry
    )

    workflow_resolver = (
        WorkflowCapabilityResolver(
            resolver
        )
    )

    requirement = CapabilityRequirement(
        capability_id=(
            "application.open"
        ),
        category=(
            CapabilityCategory.APPLICATION
        ),
        operation="application.open",
        required_inputs=frozenset({
            "application",
        }),
        required_permissions=frozenset({
            "application.launch", 
        }),
    )

    return workflow_resolver.resolve_step(
        step_id="step-1",
        requirement=requirement,
    )


def test_dynamic_plan_constructs_application_open():

    binding = (
        _build_application_open_binding()
    )

    result = (
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=binding,
            target="Chrome",
            application="Chrome",
            task="Open Chrome",
        )
    )

    assert result.constructed

    assert result.plan is not None

    assert (
        result.plan.operation
        == "application.open"
    )

    assert (
        result.plan.application
        == "Chrome"
    )

    assert (
        result.plan.target
        == "Chrome"
    )

    assert (
        result.plan.parameters[
            "_capability_id"
        ]
        == "application.open"
    )


def test_dynamic_plan_does_not_execute():

    binding = (
        _build_application_open_binding()
    )

    result = (
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=binding,
            target="Chrome",
            application="Chrome",
        )
    )

    assert result.constructed

    # Construction produces only an ActionPlan.
    # No executor or OS manager is invoked.
    assert result.plan is not None


def test_dynamic_plan_preserves_confidence():

    binding = (
        _build_application_open_binding()
    )

    result = (
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=binding,
            target="Chrome",
            application="Chrome",
        )
    )

    assert (
        result.plan.confidence
        == binding.resolved.confidence
    )


def test_dynamic_plan_preserves_capability_provider():

    binding = (
        _build_application_open_binding()
    )

    result = (
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=binding,
            target="Chrome",
            application="Chrome",
        )
    )

    assert (
        result.provider
        == "genesis.application"
    )


def test_dynamic_plan_requires_application_input():

    binding = (
        _build_application_open_binding()
    )

    try:
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=binding,
            target="Chrome",
        )
    except DynamicPlanValidationError as error:
        assert "required inputs" in str(
            error
        )
        return

    assert False, (
        "Dynamic plan construction must reject "
        "missing required capability inputs."
    )


def test_unresolved_capability_cannot_construct_plan():

    binding = (
        _build_application_open_binding()
    )

    from genesis_os.capability_resolution import (
        CapabilityResolutionStatus,
        ResolvedCapability,
    )

    unresolved = (
        type(binding)(
            step_id=binding.step_id,
            requirement=binding.requirement,
            resolved=ResolvedCapability(
                status=(
                    CapabilityResolutionStatus
                    .UNSUPPORTED
                ),
                requirement=binding.requirement,
                explanation="Unsupported.",
            ),
            metadata={},
        )
    )

    try:
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=unresolved,
            target="Chrome",
            application="Chrome",
        )
    except CapabilityNotResolvedError:
        return

    assert False, (
        "Unresolved capabilities must never become "
        "ActionPlans."
    )


def test_dynamic_plan_serializes():

    binding = (
        _build_application_open_binding()
    )

    result = (
        DynamicPlanConstructor().construct(
            step_id="step-1",
            binding=binding,
            target="Chrome",
            application="Chrome",
        )
    )

    data = result.to_dict()

    assert data["constructed"] is True

    assert (
        data["capability_id"]
        == "application.open"
    )

    assert (
        data["plan"]["operation"]
        == "application.open"
    )