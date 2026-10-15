"""
Genesis OS — Level 3.6
Capability Registry Contract
"""

from genesis_os.capability_registry import (
    Capability,
    CapabilityRegistry,
)


def test_application_open_is_registered():

    capability = CapabilityRegistry.get(
        "application.open"
    )

    assert isinstance(
        capability,
        Capability,
    )

    assert capability.operation == (
        "application.open"
    )

    assert capability.category == (
        "application"
    )

    assert capability.enabled is True


def test_application_close_is_registered():

    assert CapabilityRegistry.exists(
        "application.close"
    )


def test_application_inspect_is_registered():

    assert CapabilityRegistry.exists(
        "application.inspect"
    )


def test_supported_operation_is_classified():

    assert CapabilityRegistry.classify(
        "application.open"
    ) == "supported"


def test_unknown_operation_is_classified():

    assert CapabilityRegistry.classify(
        "something.unknown"
    ) == "unknown"


def test_empty_operation_is_invalid():

    assert CapabilityRegistry.classify(
        ""
    ) == "invalid"


def test_whitespace_operation_is_invalid():

    assert CapabilityRegistry.classify(
        "   "
    ) == "invalid"


def test_non_string_operation_is_invalid():

    assert CapabilityRegistry.classify(
        123
    ) == "invalid"


def test_application_open_is_not_dangerous():

    assert CapabilityRegistry.is_dangerous(
        "application.open"
    ) is False


def test_capability_serialization():

    capability = CapabilityRegistry.get(
        "application.open"
    )

    data = capability.to_dict()

    assert isinstance(
        data,
        dict,
    )

    assert data["operation"] == (
        "application.open"
    )

    assert data["category"] == (
        "application"
    )

    assert data["enabled"] is True


def test_registry_serialization():

    data = CapabilityRegistry.to_dict()

    assert isinstance(
        data,
        dict,
    )

    assert data["version"] == (
        CapabilityRegistry.VERSION
    )

    assert isinstance(
        data["capabilities"],
        list,
    )


def test_registry_operations_are_deterministic():

    first = CapabilityRegistry.operations()
    second = CapabilityRegistry.operations()

    assert first == second


def test_application_capabilities_are_discoverable():

    capabilities = (
        CapabilityRegistry.by_category(
            CapabilityRegistry.APPLICATION
        )
    )

    operations = {
        capability.operation
        for capability in capabilities
    }

    assert "application.open" in operations
    assert "application.close" in operations
    assert "application.inspect" in operations