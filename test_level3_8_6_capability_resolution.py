from genesis_os.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRequirement,
)

from genesis_os.capability_registry import (
    CapabilityRegistry,
)

from genesis_os.capability_resolver import (
    CapabilityResolver,
    CapabilityUnavailableError,
)

from genesis_os.default_capabilities import (
    register_default_capabilities,
)

from genesis_os.workflow_capability import (
    WorkflowCapabilityResolver,
)


def test_default_capabilities_register():

    registry = CapabilityRegistry()

    register_default_capabilities(
        registry
    )

    assert (
        registry.get(
            "filesystem.search"
        ).operation
        == "search"
    )


def test_capability_requirement_matches():

    registry = CapabilityRegistry()

    register_default_capabilities(
        registry
    )

    requirement = CapabilityRequirement(
        capability_id=(
            "filesystem.search"
        ),
        category=(
            CapabilityCategory.FILESYSTEM
        ),
        operation="search",
        required_inputs=frozenset({
            "query",
        }),
        required_permissions=frozenset({
            "filesystem.read",
        }),
    )

    candidates = registry.candidates(
        requirement
    )

    assert candidates

    assert (
        candidates[0].capability_id
        == "filesystem.search"
    )


def test_capability_resolver_selects_capability():

    registry = CapabilityRegistry()

    register_default_capabilities(
        registry
    )

    resolver = CapabilityResolver(
        registry
    )

    requirement = CapabilityRequirement(
        capability_id=(
            "application.launch"
        ),
        category=(
            CapabilityCategory.APPLICATION
        ),
        operation="launch",
        required_inputs=frozenset({
            "application",
        }),
        required_permissions=frozenset({
            "application.launch",
        }),
    )

    resolved = resolver.resolve(
        requirement
    )

    assert (
        resolved.capability.capability_id
        == "application.launch"
    )

    assert resolved.confidence >= 0.80


def test_missing_capability_fails_safely():

    registry = CapabilityRegistry()

    resolver = CapabilityResolver(
        registry
    )

    requirement = CapabilityRequirement(
        capability_id=(
            "unknown.operation"
        ),
        category=(
            CapabilityCategory.GENERAL
        ),
        operation="unknown",
    )

    try:
        resolver.resolve(
            requirement
        )
    except CapabilityUnavailableError:
        return

    assert False, (
        "Missing capabilities must fail "
        "explicitly."
    )


def test_workflow_capability_binding():

    registry = CapabilityRegistry()

    register_default_capabilities(
        registry
    )

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
            "filesystem.open"
        ),
        category=(
            CapabilityCategory.FILESYSTEM
        ),
        operation="open",
        required_inputs=frozenset({
            "path",
        }),
        required_permissions=frozenset({
            "filesystem.read",
        }),
    )

    binding = (
        workflow_resolver.resolve_step(
            step_id="step-2",
            requirement=requirement,
        )
    )

    assert (
        binding.step_id
        == "step-2"
    )

    assert (
        binding.resolved.capability
        .capability_id
        == "filesystem.open"
    )


def test_runtime_context_contains_capability_system():

    from genesis_os.workflow_runtime_context import (
        WorkflowRuntimeContext,
    )

    runtime = (
        WorkflowRuntimeContext(
            "capability-test"
        )
    )

    requirement = CapabilityRequirement(
        capability_id=(
            "filesystem.search"
        ),
        category=(
            CapabilityCategory.FILESYSTEM
        ),
        operation="search",
        required_inputs=frozenset({
            "query",
        }),
        required_permissions=frozenset({
            "filesystem.read",
        }),
    )

    binding = (
        runtime.resolve_capability(
            step_id="step-1",
            requirement=requirement,
        )
    )

    assert (
        binding.resolved.capability
        .capability_id
        == "filesystem.search"
    )